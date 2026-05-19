"""
Feature Request Servisi

İŞ AKIŞLARI
-----------
  submit_request()          → Haftalık hak kontrolü → embed → benzerlik kontrolü → fraud → kaydet
  update_request()          → Mevcut kaydı yeni vektörle güncelle (düzenleme akışı)
  check_weekly_quota()      → Bu hafta kaç submit hakkı kaldı?
  find_similar_this_week()  → Bu haftaki kayıtlarla cosine similarity karşılaştırması
  detect_fraud()            → Farklı kullanıcılardan gelen benzer vektörleri tespit et
  run_clustering_pipeline()    → status=embedded → L2 norm → UMAP → HDBSCAN → label → DB yaz
  retry_clustering_failed()    → status=clustering_failed → status=embedded (pipeline'a tekrar girer)
  generate_admin_report()   → Kümelenmiş verilerden Groq ile Türkçe rapor üret

BAĞIMLILIKLAR
-------------
  VectorClient    → Embedding (sentence-transformers)
  GroqClient      → Cluster label ve rapor üretimi (LLM)
  DatabaseManager → Async session yönetimi

DÖNÜŞ TİPLERİ (submit_request)
--------------------------------
  {"status": "created",         "request_id": "FRQ-..."}
  {"status": "similar_found",   "existing_id": "FRQ-...", "existing_text": "..."}
  {"status": "quota_exceeded",  "used": 2, "max": 2}
"""

import logging
import os
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

# Numba önce NUMBA_CACHE_DIR ile yazılabilir bir kök arar; yoksa site-packages/__pycache__
# denenir (Docker'da genelde yazılamaz → "no locator available").
os.environ.setdefault(
    "NUMBA_CACHE_DIR",
    os.path.join(tempfile.gettempdir(), "numba-cache"),
)

import hdbscan
import numpy as np
import umap
from sklearn.cluster import AgglomerativeClustering

from packages.clients.groq import GroqClient
from packages.database.models.feature_request import FeatureClusterLabel, FeatureRequest
from packages.database.repository.feature_request import (
    FeatureClusterLabelRepository,
    FeatureRequestRepository,
)
from packages.settings import get_settings
from packages.vector import VectorClient
from services.feature_request_service.logger import get_logger
from services.feature_request_service.utils.notifications import (
    NotificationType,
    send_notification,
)

# None ise batch büyüklüğüne göre dinamik hesaplama kullanılır.
# Kalibrasyon tamamlanınca buraya ClusteringParams(...) değeri girilir.


@dataclass
class ClusteringParams:
    """UMAP ve HDBSCAN için parametre kümesi."""

    min_cluster_size: int
    min_samples: int
    n_components: int
    n_neighbors: int

    @classmethod
    def from_batch_size(cls, n: int) -> "ClusteringParams":
        """Batch büyüklüğüne göre dinamik parametre hesaplaması."""
        min_cluster_size = max(3, int(n * 0.025))
        min_samples = max(2, int(min_cluster_size * 0.6))
        n_components = min(10, max(5, int(np.log2(max(n, 2)))))
        n_neighbors = min(15, max(5, int(np.sqrt(n))))
        return cls(min_cluster_size, min_samples, n_components, n_neighbors)


FIXED_CLUSTERING_PARAMS: ClusteringParams | None = None

# ---------------------------------------------------------------------------
# Fallback algoritma eşik değerleri
# ---------------------------------------------------------------------------

DIRECT_DUMP_MAX_RECORDS: int = 5
"""Bu sayı veya daha az embedded kayıt varsa kümeleme yapılmaz; kayıtlar
rapora direkt listelenir ve reported olarak işaretlenir."""

HDBSCAN_MIN_RECORDS: int = 20
"""Bu sayıdan az embedded kayıt varsa UMAP atlanır, Agglomerative Clustering
ön izleme modunda çalışır (status değişmez, kayıtlar sonraki haftaya taşınır)."""

FALLBACK_DISTANCE_THRESHOLD: float = 0.7
"""Agglomerative Clustering için cosine distance eşiği.
cosine distance 0.7 → cosine similarity ≈ 0.755.
Linkage: average + metric: cosine (L2 normalizasyon gerekmez)."""


@dataclass
class _RecordSnapshot:
    """Session bağımsız hafif kayıt temsili.

    SQLAlchemy ORM nesneleri bir oturum kapandıktan sonra "detached" hale gelir
    ve lazy-load tetikleyebilir. Oturumlar arası veri taşımak için bu sınıf
    ilgili primitive alanları kopyalar; generate_admin_report ve preview
    yapıları bu nesneleri ORM nesnesiyle aynı attribute adları üzerinden tüketir.
    """

    id: str
    request_raw: str
    cluster_id: int | None = None
    fraud_score: float | None = None
    user_id: str = ""


def _umap_params_for_sample_count(
    n_samples: int, params: ClusteringParams
) -> tuple[int, int, dict]:
    """
    UMAP spektral başlatma scipy eigsh ile k < N ister; n_components ve n_neighbors üst sınırı taşarsa TypeError oluşur (az kayıt).
    """
    # Komşu sayısı en fazla n_samples - 1; en az 2 (UMAP dokümantasyonu ile uyumlu küçük alt sınır)
    n_neighbors = max(2, min(params.n_neighbors, n_samples - 1))
    # Gömü boyutu örnekten küçük olmalı; dar marj (n_samples - 1) ile kes
    n_components = max(2, min(params.n_components, n_samples - 1))
    extra: dict = {}
    if n_samples < 15:
        extra["init"] = "random"
    return n_neighbors, n_components, extra


_CLUSTER_ID_SAMPLE_LIMIT = 12
"""clustering.log içinde küme başına en fazla kaç talep ID'si örneklenir."""


def _clustering_trace(logger: logging.Logger, phase: str, **payload: Any) -> None:
    """
    ``logs/feature_request_service/clustering.log`` dosyasına tek satır JSON yazar
    (ClusteringFormatter). Takip: phase + zaman damgası + payload.
    """
    data: dict[str, Any] = {
        "phase": phase,
        "at": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    logger.info("[FR-clustering] %s", phase, extra={"clustering": data})


class FeatureRequestService:
    """
    `/cemilimyapar` komutunun iş mantığını yöneten servis sınıfı.

    Tüm infrastructure client'larını constructor'da oluşturur.
    """

    def __init__(self, db_manager) -> None:
        self.logger = get_logger("feature_request_service.service")
        self.vector_client = VectorClient()
        self.groq_client = GroqClient()
        self.db = db_manager

    # SUBMIT AKIŞI

    async def submit_request(self, user_id: str, raw_text: str) -> dict[str, Any]:
        """
        Ana submit akışı. Sırasıyla şunları yapar:

        1. Haftalık hak kontrolü → dolmuşsa `quota_exceeded` döndür.
        2. Metni embed et.
        3. Bu haftaki kayıtlarla benzerlik kontrolü → benzer varsa `similar_found` döndür.
        4. Fraud tespiti.
        5. DB'ye kaydet → `created` döndür.

        Args:
            user_id: Slack kullanıcı ID'si (`slack_users.slack_id`).
            raw_text: Modal'dan gelen ham talep metni.

        Returns:
            status="created"       → {"status": "created", "request_id": "FRQ-..."}
            status="similar_found" → {"status": "similar_found", "existing_id": ..., "existing_text": ..., "pending_id": ...}
            status="exact_match"   → {"status": "exact_match", "existing_id": ..., "existing_text": ...}
            status="quota_exceeded"→ {"status": "quota_exceeded", "used": N, "max": N}
        """
        from packages.database.repository.slack import SlackUserRepository

        async with self.db.session() as session:
            # 0. Sync Slack user basic record
            slack_repo = SlackUserRepository(session)
            await slack_repo.get_or_create(slack_id=user_id)

            repo = FeatureRequestRepository(session)
            cfg = get_settings()

            # 1. Haftalık hak kontrolü
            used = await self.check_weekly_quota(user_id, repo)
            if used >= cfg.feature_request_weekly_quota:
                _clustering_trace(
                    self.logger,
                    "submit_quota_blocked",
                    user_id=user_id,
                    used_this_window=used,
                    quota_max=cfg.feature_request_weekly_quota,
                )
                self.logger.info(
                    "Haftalık kota aşıldı.", extra={"user_id": user_id, "used": used}
                )
                return {
                    "status": "quota_exceeded",
                    "used": used,
                    "max": cfg.feature_request_weekly_quota,
                }

            # 2. Embed
            try:
                vector = self.vector_client.embed(raw_text)
                _clustering_trace(
                    self.logger,
                    "submit_embed_ok",
                    user_id=user_id,
                    embedding_dims=list(vector.shape)
                    if hasattr(vector, "shape")
                    else None,
                    text_chars=len(raw_text or ""),
                )
            except Exception as exc:
                self.logger.error(f"Embed hatası: {exc}", exc_info=True)
                # Embedding başarısız olsa dahi kaydı `embedding_failed` statusuyla ekle
                failed_req = FeatureRequest(
                    user_id=user_id,
                    request_raw=raw_text,
                    status="embedding_failed",
                )
                session.add(failed_req)
                await session.flush()
                return {"status": "created", "request_id": failed_req.id}

            # 3. Benzerlik kontrolü
            similar_record, similarity_score = await self.find_similar_this_week(
                user_id, vector, repo
            )
            if similar_record is not None:
                if similarity_score >= cfg.feature_request_similarity_exact:
                    _clustering_trace(
                        self.logger,
                        "submit_similarity_exact_match",
                        user_id=user_id,
                        matched_request_id=similar_record.id,
                        cosine_similarity=round(float(similarity_score), 6),
                        threshold_exact=cfg.feature_request_similarity_exact,
                    )
                    self.logger.info(
                        "Birebir aynı (exact match) kayıt bulundu.",
                        extra={
                            "user_id": user_id,
                            "similar_id": similar_record.id,
                            "score": similarity_score,
                        },
                    )
                    return {
                        "status": "exact_match",
                        "existing_id": similar_record.id,
                        "existing_text": similar_record.request_raw,
                    }
                elif similarity_score >= cfg.feature_request_similarity_warning:
                    _clustering_trace(
                        self.logger,
                        "submit_similarity_warning_zone",
                        user_id=user_id,
                        matched_request_id=similar_record.id,
                        cosine_similarity=round(float(similarity_score), 6),
                        threshold_warning=cfg.feature_request_similarity_warning,
                        threshold_exact=cfg.feature_request_similarity_exact,
                    )
                    self.logger.info(
                        "Benzer kayıt bulundu (gri alan).",
                        extra={
                            "user_id": user_id,
                            "similar_id": similar_record.id,
                            "score": similarity_score,
                        },
                    )
                    # 4. Fraud tespiti
                    fraud_score = await self.detect_fraud(vector, user_id, repo)

                    # Varolan eski pending_bypass taslaklarını temizle (race condition ve çift tıklama önleme)
                    await repo.delete_pending_bypass(user_id)

                    # 5. pending_bypass olarak kaydet
                    pending_request = FeatureRequest(
                        user_id=user_id,
                        request_raw=raw_text,
                        request_embedded=vector.tolist(),
                        status="pending_bypass",
                        fraud_score=fraud_score,
                    )
                    session.add(pending_request)
                    await session.flush()

                    _clustering_trace(
                        self.logger,
                        "submit_created_pending_bypass",
                        user_id=user_id,
                        pending_id=pending_request.id,
                        similar_to=similar_record.id,
                        fraud_score=fraud_score,
                    )

                    return {
                        "status": "similar_found",
                        "existing_id": similar_record.id,
                        "existing_text": similar_record.request_raw,
                        "pending_id": pending_request.id,
                    }

            # 4. Fraud tespiti
            fraud_score = await self.detect_fraud(vector, user_id, repo)

            # 5. Kaydet
            new_request = FeatureRequest(
                user_id=user_id,
                request_raw=raw_text,
                request_embedded=vector.tolist(),
                status="embedded",
                fraud_score=fraud_score,
            )
            session.add(new_request)
            await session.flush()

            _clustering_trace(
                self.logger,
                "submit_created_embedded",
                user_id=user_id,
                request_id=new_request.id,
                fraud_score=fraud_score,
                note="Kayıt embedded; kümeleme pipeline bu talebi bekleyecek.",
            )
            self.logger.info(
                "Yeni feature request kaydedildi.",
                extra={"user_id": user_id, "request_id": new_request.id},
            )
            return {"status": "created", "request_id": new_request.id}

    async def get_request_text(self, request_id: str) -> str:
        """
        Kullanıcının düzenleme (edit) işlemi için veritabanından mevcut request_raw değerini getirir.
        Kayıt bulunamazsa ValueError fırlatır.
        """
        async with self.db.session() as session:
            repo = FeatureRequestRepository(session)
            request = await repo.get(request_id)
            if not request:
                raise ValueError(
                    f"ID'si '{request_id}' olan Feature Request kaydı bulunamadı."
                )
            return request.request_raw

    async def approve_pending_request(self, pending_id: str) -> dict[str, Any]:
        """
        'Hayır, farklı' butonuyla bypass edilmek istenen pending_bypass
        statüsündeki kaydın statüsünü 'embedded' yaparak sisteme dahil eder.
        """
        async with self.db.session() as session:
            from packages.database.repository.feature_request import (
                FeatureRequestRepository,
            )

            repo = FeatureRequestRepository(session)
            req = await repo.get(pending_id)
            if not req:
                return {"status": "not_found"}

            if req.status == "pending_bypass":
                req.status = "embedded"
                await session.flush()
                self.logger.info(
                    "Pending bypass onaylandı.", extra={"request_id": pending_id}
                )
                return {"status": "approved"}
            else:
                return {"status": "invalid_status", "current_status": req.status}

    async def update_request(self, request_id: str, new_text: str) -> dict[str, Any]:
        """
        Mevcut bir talebi günceller (düzenleme akışı — 'Evet, düzenleyeyim' butonu).

        Yeni metin için yeni bir embedding üretir, kaydı günceller ve
        status'u 'embedded' olarak sıfırlar (clustering kuyruğuna geri girer).

        Args:
            request_id: Güncellenecek FeatureRequest'in id'si.
            new_text:   Düzenleme modal'ından gelen yeni ham metin.

        Returns:
            {"status": "updated", "request_id": "FRQ-..."}
            {"status": "not_found"}
        """
        async with self.db.session() as session:
            repo = FeatureRequestRepository(session)
            request = await repo.get(request_id)

            if request is None:
                self.logger.warning(
                    "Güncellenecek kayıt bulunamadı.", extra={"request_id": request_id}
                )
                return {"status": "not_found"}

            try:
                new_vector = self.vector_client.embed(new_text)
                new_embedded = new_vector.tolist()
            except Exception as exc:
                self.logger.error(f"Güncelleme embed hatası: {exc}", exc_info=True)
                new_embedded = None

            request.request_raw = new_text
            request.request_embedded = new_embedded
            request.status = "embedded" if new_embedded else "embedding_failed"
            request.cluster_id = None  # Önceki cluster atamasını sıfırla
            await repo.update(request)

            self.logger.info(
                "Feature request güncellendi.", extra={"request_id": request_id}
            )
            return {"status": "updated", "request_id": request_id}

    # ==========================================================================
    # YARDIMCI METODLAR
    # ==========================================================================

    async def check_weekly_quota(
        self,
        user_id: str,
        repo: FeatureRequestRepository | None = None,
    ) -> int:
        """
        Kullanıcının bu hafta kaç submit kullandığını döndürür.

        Args:
            user_id: Sorgulanacak kullanıcının Slack ID'si.
            repo:    Opsiyonel — halihazırda açık bir session varsa inject edilir.
                     None ise yeni session açılır.

        Returns:
            Kullanılan submit sayısı (int). `get_settings().feature_request_weekly_quota` ile karşılaştırılmalı.
        """
        if repo is not None:
            records = await repo.list_by_user_this_week(user_id)
            return len(records)

        async with self.db.session() as session:
            records = await FeatureRequestRepository(session).list_by_user_this_week(
                user_id
            )
            return len(records)

    async def find_similar_this_week(
        self,
        user_id: str,
        new_vector: np.ndarray,
        repo: FeatureRequestRepository | None = None,
    ) -> tuple[FeatureRequest | None, float]:
        """
        Kullanıcının bu haftaki kayıtları arasında new_vector'e ne kadar benzediğini ölçer
        ve en yüksek benzerlik skoruna sahip kaydı ile skorunu döner.

        Args:
            user_id:    Arama yapılacak kullanıcının Slack ID'si.
            new_vector: Yeni talebin embedding vektörü.
            repo:       Opsiyonel inject edilmiş repository.

        Returns:
            (En benzer FeatureRequest kaydı, Benzerlik Skoru) tuple olarak döner. Yoksa (None, 0.0) döner.
        """
        if repo is not None:
            existing = await repo.list_embedded_vectors(user_id)
        else:
            async with self.db.session() as session:
                existing = await FeatureRequestRepository(
                    session
                ).list_embedded_vectors(user_id)

        cfg = get_settings()
        _clustering_trace(
            self.logger,
            "similarity_week_scan_start",
            user_id=user_id,
            candidate_embedded_records=len(existing),
            thresholds={
                "similarity_exact": cfg.feature_request_similarity_exact,
                "similarity_warning": cfg.feature_request_similarity_warning,
            },
        )

        max_similarity = 0.0
        most_similar_record = None
        compared = 0

        for record in existing:
            if record.request_embedded is None:
                continue
            try:
                compared += 1
                existing_vec = np.array(record.request_embedded, dtype=np.float32)
                similarity = self.vector_client.cosine_similarity(
                    new_vector, existing_vec
                )
                if similarity > max_similarity:
                    max_similarity = similarity
                    most_similar_record = record
            except Exception as exc:
                self.logger.warning(
                    f"Benzerlik hesaplama hatası (atlanıyor): {exc}",
                    extra={"record_id": record.id},
                )
                continue

        if most_similar_record:
            self.logger.info(
                f"Benzerlik analizi tamamlandı (max_sim={max_similarity:.4f}).",
                extra={
                    "user_id": user_id,
                    "existing_id": most_similar_record.id,
                    "score": max_similarity,
                },
            )
            _clustering_trace(
                self.logger,
                "similarity_week_best",
                user_id=user_id,
                compared_pairs=compared,
                best_match_request_id=most_similar_record.id,
                max_cosine_similarity=round(float(max_similarity), 6),
            )
        else:
            _clustering_trace(
                self.logger,
                "similarity_week_no_vectors",
                user_id=user_id,
                compared_pairs=compared,
                note="Karşılaştırılabilir gömülü kayıt yok veya hepsi atlandı.",
            )

        return most_similar_record, float(max_similarity)

    async def detect_fraud(
        self,
        new_vector: np.ndarray,
        user_id: str,
        repo: FeatureRequestRepository | None = None,
    ) -> float:
        """
        Farklı kullanıcılardan gelen rolling penceredeki embedded taleplerle
        new_vector'ü karşılaştırır ve bir fraud_score üretir.

        Fraud score = benzer kayıt sayısı / toplam karşılaştırılan kayıt sayısı.
        Eşiğin üstünde benzerlik gösteren kayıt yoksa 0.0 döner.

        Args:
            new_vector: Değerlendirilecek vektör.
            user_id:    Kendi kayıtlarını eşleşme listesinden çıkarmak için.
            repo:       Opsiyonel inject edilmiş repository.

        Returns:
            0.0–1.0 arası fraud skoru.
        """
        cfg = get_settings()
        days = cfg.feature_request_rolling_window_days
        since = datetime.now(timezone.utc) - timedelta(days=days)
        if repo is not None:
            others = await repo.list_embedded_others_since(user_id, since)
        else:
            async with self.db.session() as session:
                others = await FeatureRequestRepository(
                    session
                ).list_embedded_others_since(user_id, since)

        if not others:
            _clustering_trace(
                self.logger,
                "fraud_scan_skipped",
                user_id=user_id,
                reason="rolling_pencerede_baska_kullanici_embedded_yok",
                rolling_days=days,
            )
            return 0.0

        similar_count = 0
        fraud_thresh = cfg.feature_request_fraud_threshold
        hits: list[dict[str, Any]] = []

        _clustering_trace(
            self.logger,
            "fraud_scan_start",
            user_id=user_id,
            pool_other_users_records=len(others),
            fraud_similarity_threshold=fraud_thresh,
            window_since_utc=since.isoformat(),
        )

        for record in others:
            try:
                other_vec = np.array(record.request_embedded, dtype=np.float32)
                similarity = self.vector_client.cosine_similarity(new_vector, other_vec)
                if similarity >= fraud_thresh:
                    similar_count += 1
                    hits.append(
                        {
                            "request_id": record.id,
                            "other_user_id": record.user_id,
                            "cosine": round(float(similarity), 6),
                        }
                    )
            except Exception:
                continue

        score = similar_count / len(others)
        _clustering_trace(
            self.logger,
            "fraud_scan_done",
            user_id=user_id,
            compared=len(others),
            matches_above_threshold=similar_count,
            fraud_ratio=round(score, 6),
            threshold=fraud_thresh,
            sample_hits=hits[:15],
        )
        if score > 0:
            self.logger.warning(
                f"Fraud tespit edildi (score={score:.3f}).",
                extra={"user_id": user_id, "similar_count": similar_count},
            )
        return round(score, 4)

    # ==========================================================================
    # CLUSTERING PIPELINE
    # ==========================================================================

    async def run_clustering_pipeline(self, is_preview: bool = False) -> dict[str, Any]:
        """
        status='embedded' olan tüm kayıtları kümeleme pipeline'ından geçirir.

        Pipeline sırası:
          1. status='embedded' kayıtları çek
          2. BLOB → numpy (N, 768)
          3. L2 normalizasyon
          4. UMAP boyut indirgeme (768 → UMAP_N_COMPONENTS)
          5. HDBSCAN kümeleme
          6. cluster_id'leri DB'ye yaz (status → 'clustered' / 'clustering_failed')
          7. Yeni cluster'lar için Groq label üret → feature_cluster_labels

        Returns:
            {
              "clustered": N,      # Başarıyla atanan kayıt sayısı
              "noise": M,          # Kümeye atanamayan (HDBSCAN -1) kayıt sayısı
              "new_labels": K,     # Bu çalıştırmada üretilen yeni label sayısı
            }
        """
        async with self.db.session() as session:
            fr_repo = FeatureRequestRepository(session)
            fcl_repo = FeatureClusterLabelRepository(session)

            embedded = await fr_repo.list_by_status("embedded")
            if not embedded:
                _clustering_trace(
                    self.logger,
                    "pipeline_abort",
                    reason="no_embedded_rows",
                    is_preview=is_preview,
                )
                self.logger.info("Kümelenecek kayıt yok.")
                return {
                    "clustered": 0,
                    "noise": 0,
                    "new_labels": 0,
                    "preview_records": [],
                    "preview_labels": {},
                }

            # --- Primitive kopyalar: session kapandıktan sonra ORM nesnelerine erişilemez ---
            raw_texts: dict[str, str] = {}
            retry_counts: dict[str, int] = {}
            fraud_scores: dict[str, float | None] = {}
            user_ids: dict[str, str] = {}

            vectors: list = []
            valid_ids: list[str] = []
            invalid_record_ids: list[str] = []

            for record in embedded:
                raw_texts[record.id] = record.request_raw
                retry_counts[record.id] = record.retry_count or 0
                fraud_scores[record.id] = record.fraud_score
                user_ids[record.id] = record.user_id

                if record.request_embedded is None:
                    invalid_record_ids.append(record.id)
                    continue
                try:
                    vec = np.array(record.request_embedded, dtype=np.float32)
                    vectors.append(vec)
                    valid_ids.append(record.id)
                except Exception as exc:
                    invalid_record_ids.append(record.id)
                    self.logger.warning(
                        f"BLOB okuma hatası, atlanıyor: {exc}",
                        extra={"record_id": record.id},
                    )

            skipped_embed = len(embedded) - len(vectors)
            _clustering_trace(
                self.logger,
                "pipeline_vectors_ready",
                is_preview=is_preview,
                embedded_rows=len(embedded),
                valid_vectors=len(vectors),
                skipped_invalid_blob=skipped_embed,
                sample_request_ids=valid_ids[:20],
            )

            n = len(vectors)

            # ──────────────────────────────────────────────────────────────
            # Yol 1 — Direkt Listeleme (n ≤ DIRECT_DUMP_MAX_RECORDS)
            # Kümeleme yapılmaz; kayıtlar rapora direkt listelenir ve
            # reported olarak işaretlenir.
            # ──────────────────────────────────────────────────────────────
            if n <= DIRECT_DUMP_MAX_RECORDS:
                _clustering_trace(
                    self.logger,
                    "pipeline_direct_list",
                    reason="too_few_for_clustering",
                    n=n,
                    threshold=DIRECT_DUMP_MAX_RECORDS,
                )
                self.logger.info(
                    f"Direkt listeleme yolu (n={n} ≤ {DIRECT_DUMP_MAX_RECORDS})."
                )
                direct_records = [
                    _RecordSnapshot(
                        id=rid,
                        request_raw=raw_texts[rid],
                        fraud_score=fraud_scores[rid],
                        user_id=user_ids[rid],
                    )
                    for rid in valid_ids
                ]
                if not is_preview:
                    await fr_repo.mark_reported(valid_ids)
                    if invalid_record_ids:
                        for rid in invalid_record_ids:
                            r = await fr_repo.get(rid)
                            if r:
                                r.status = "embedding_failed"
                        await session.flush()
                return {
                    "pipeline_type": "direct_list",
                    "clustered": 0,
                    "noise": 0,
                    "new_labels": 0,
                    "direct_records": direct_records,
                    "preview_records": [],
                    "preview_labels": {},
                }

            # ──────────────────────────────────────────────────────────────
            # Yol 2 — Agglomerative Ön İzleme (DIRECT_DUMP_MAX_RECORDS < n < HDBSCAN_MIN_RECORDS)
            # UMAP atlanır, ham vektörler üzerinde Agglomerative Clustering
            # çalışır. Status değişmez; kayıtlar sonraki haftaya taşınır.
            # ──────────────────────────────────────────────────────────────
            if n < HDBSCAN_MIN_RECORDS:
                _clustering_trace(
                    self.logger,
                    "pipeline_agglomerative_preview",
                    n=n,
                    distance_threshold=FALLBACK_DISTANCE_THRESHOLD,
                    linkage="average",
                    metric="cosine",
                )
                self.logger.info(
                    f"Agglomerative ön izleme yolu (n={n}, "
                    f"eşik={FALLBACK_DISTANCE_THRESHOLD})."
                )
                raw_matrix = np.array(vectors, dtype=np.float32)
                agg = AgglomerativeClustering(
                    n_clusters=None,
                    distance_threshold=FALLBACK_DISTANCE_THRESHOLD,
                    metric="cosine",
                    linkage="average",
                )
                agg_labels = agg.fit_predict(raw_matrix)

                # Geçersiz embedding'leri session içinde işaretle (session kısa ömürlü, Groq yok)
                if invalid_record_ids and not is_preview:
                    for rid in invalid_record_ids:
                        r = await fr_repo.get(rid)
                        if r:
                            r.status = "embedding_failed"
                    await session.flush()

                # Groq için gereken veriyi primitive olarak topla; session kapandıktan sonra kullanılacak
                agg_cluster_data: dict[int, tuple[list[str], list[int]]] = {}
                for cid in set(int(lb) for lb in agg_labels):
                    c_indices = [i for i, lb in enumerate(agg_labels) if lb == cid]
                    s_ids = [valid_ids[i] for i in c_indices[:5]]
                    s_texts = [raw_texts[sid] for sid in s_ids]
                    agg_cluster_data[cid] = (s_texts, c_indices)

            # ──────────────────────────────────────────────────────────────
            # Yol 3 — HDBSCAN öncesi: mevcut cluster label ID'lerini pre-fetch et
            # (Groq çağrısı session dışında olacak; hangi cluster'ların label'ı
            #  var sorusu session kapanmadan cevaplanmalı)
            # ──────────────────────────────────────────────────────────────
            existing_cluster_ids: set[int] = await fcl_repo.list_all_cluster_ids()

        # ═══════════════════════════════════════════════════════════════════
        # SESSION 1 KAPANDI — ORM nesnelerine artık erişilmez
        # Bundan sonra yalnızca primitive kopyalar (raw_texts, valid_ids vb.)
        # ve numpy dizileri kullanılır.
        # ═══════════════════════════════════════════════════════════════════

        # --- Yol 2 tamamlama: Groq çağrısı (session-free) ---
        if n < HDBSCAN_MIN_RECORDS:
            preview_records_agg: list[_RecordSnapshot] = []
            preview_labels_agg: dict[int, str] = {}

            for cid, (s_texts, c_indices) in agg_cluster_data.items():
                label_text = await self._generate_cluster_label(cid, s_texts)
                preview_labels_agg[cid] = label_text
                for idx in c_indices:
                    preview_records_agg.append(
                        _RecordSnapshot(
                            id=valid_ids[idx],
                            request_raw=raw_texts[valid_ids[idx]],
                            cluster_id=cid,
                            fraud_score=fraud_scores[valid_ids[idx]],
                            user_id=user_ids[valid_ids[idx]],
                        )
                    )

            # Status DEĞİŞMEZ — embedded kalır, sonraki haftaya taşınır
            return {
                "pipeline_type": "agglomerative_preview",
                "clustered": len(preview_records_agg),
                "noise": 0,
                "new_labels": len(preview_labels_agg),
                "preview_records": preview_records_agg,
                "preview_labels": preview_labels_agg,
            }

        # ──────────────────────────────────────────────────────────────
        # Yol 3 — HDBSCAN Pipeline (n ≥ HDBSCAN_MIN_RECORDS)
        # Faz 2: L2 norm → UMAP → HDBSCAN → Groq  (session yok)
        # ──────────────────────────────────────────────────────────────

        # --- L2 normalizasyon ---
        matrix = np.array(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)  # sıfır bölme koruması
        matrix = matrix / norms

        # --- Parametreler ---
        params = FIXED_CLUSTERING_PARAMS or ClusteringParams.from_batch_size(
            len(vectors)
        )

        _clustering_trace(
            self.logger,
            "pipeline_params",
            is_preview=is_preview,
            source="fixed" if FIXED_CLUSTERING_PARAMS else "dynamic_from_batch",
            hdbscan_min_cluster_size=params.min_cluster_size,
            hdbscan_min_samples=params.min_samples,
            umap_n_components_requested=params.n_components,
            umap_n_neighbors_requested=params.n_neighbors,
            batch_size=len(vectors),
        )

        compute_error: Exception | None = None
        labels = None
        new_cluster_labels: dict[int, str] = {}
        groq_labels_detail: dict[str, Any] = {}
        reduced = None
        n_neighbors_umap = n_components_umap = 0
        umap_extra: dict = {}

        try:
            # --- UMAP boyut indirgeme ---
            n_samples = len(vectors)
            n_neighbors_umap, n_components_umap, umap_extra = (
                _umap_params_for_sample_count(n_samples, params)
            )
            _clustering_trace(
                self.logger,
                "pipeline_umap_start",
                matrix_shape=list(matrix.shape),
                n_samples=n_samples,
                effective_n_neighbors=n_neighbors_umap,
                effective_n_components=n_components_umap,
                init=str(umap_extra.get("init", "spectral_default")),
            )
            self.logger.info(
                "UMAP çalışıyor: %s → (%s, %s) n_neighbors=%s init=%s",
                matrix.shape,
                n_samples,
                n_components_umap,
                n_neighbors_umap,
                umap_extra.get("init", "default"),
            )
            reducer = umap.UMAP(
                n_components=n_components_umap,
                metric="cosine",
                n_neighbors=n_neighbors_umap,
                random_state=42,
                **umap_extra,
            )
            reduced = reducer.fit_transform(matrix)
            _clustering_trace(
                self.logger,
                "pipeline_umap_done",
                reduced_shape=list(reduced.shape),
            )

            # --- HDBSCAN kümeleme ---
            _clustering_trace(
                self.logger,
                "pipeline_hdbscan_start",
                min_cluster_size=params.min_cluster_size,
                min_samples=params.min_samples,
                metric="euclidean_on_umap_space",
            )
            self.logger.info("HDBSCAN kümeleme başlatılıyor...")
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=params.min_cluster_size,
                min_samples=params.min_samples,
                metric="euclidean",
                prediction_data=True,
            )
            labels = clusterer.fit_predict(reduced)  # -1 = noise
            uniq, counts = np.unique(labels, return_counts=True)
            label_dist = {
                int(k): int(v) for k, v in zip(uniq.tolist(), counts.tolist())
            }
            _clustering_trace(
                self.logger,
                "pipeline_hdbscan_done",
                label_distribution=label_dist,
                noise_points=int(label_dist.get(-1, 0)),
                distinct_clusters=len([k for k in label_dist if k != -1]),
            )

            # --- Groq label üretimi (session-free) ---
            unique_clusters = set(int(lbl) for lbl in labels if lbl != -1)
            for cid in unique_clusters:
                if cid in existing_cluster_ids:
                    groq_labels_detail[str(cid)] = {"source": "existing_db"}
                    continue

                cluster_indices = [i for i, lbl in enumerate(labels) if lbl == cid]
                sample_ids = [valid_ids[i] for i in cluster_indices[:5]]
                sample_texts = [raw_texts[sid] for sid in sample_ids]

                label_text = await self._generate_cluster_label(cid, sample_texts)
                new_cluster_labels[cid] = label_text
                groq_labels_detail[str(cid)] = {
                    "source": "groq_generated",
                    "label": (label_text or "")[:400],
                    "sample_request_ids": sample_ids,
                    "sample_text_chars": [len(t or "") for t in sample_texts],
                }

        except Exception as exc:
            compute_error = exc
            _clustering_trace(
                self.logger,
                "pipeline_compute_failed",
                error=str(exc),
                request_ids_affected=valid_ids,
            )
            self.logger.error(f"Pipeline hesaplama hatası: {exc}", exc_info=True)

        # ═══════════════════════════════════════════════════════════════════
        # SESSION 2 — Yaz (her durumda açılır: hata veya başarı)
        # ═══════════════════════════════════════════════════════════════════
        async with self.db.session() as session:
            fr_repo = FeatureRequestRepository(session)
            fcl_repo = FeatureClusterLabelRepository(session)

            # Geçersiz embedding'leri işaretle (tüm yollarda)
            if invalid_record_ids and not is_preview:
                for rid in invalid_record_ids:
                    r = await fr_repo.get(rid)
                    if r:
                        r.status = "embedding_failed"
                await session.flush()

            # Hesaplama (UMAP / HDBSCAN / Groq) başarısız olduysa hata yolu
            if compute_error is not None:
                if not is_preview:
                    for rid in valid_ids:
                        r = await fr_repo.get(rid)
                        if r:
                            r.status = "clustering_failed"
                    await session.flush()
                return {
                    "clustered": 0,
                    "noise": len(valid_ids),
                    "new_labels": 0,
                    "preview_records": [],
                    "preview_labels": {},
                }

            # --- DB güncelleme ---
            clustered_count = 0
            noise_count = 0
            noise_ids_sample: list[str] = []
            unmatched_ids: list[str] = []

            preview_records: list[_RecordSnapshot] = []
            preview_labels: dict[int, str] = {}

            member_map: defaultdict[int, list[str]] = defaultdict(list)

            for req_id, cluster_label in zip(valid_ids, labels):
                if cluster_label == -1:
                    noise_count += 1
                    if len(noise_ids_sample) < 25:
                        noise_ids_sample.append(req_id)
                    if not is_preview:
                        new_count = await fr_repo.increment_retry_count(req_id)
                        if new_count >= 3:
                            unmatched_ids.append(req_id)
                    continue
                member_map[int(cluster_label)].append(req_id)
                if not is_preview:
                    await fr_repo.update_cluster(req_id, int(cluster_label))
                    await fr_repo.reset_retry_count(req_id)
                else:
                    preview_records.append(
                        _RecordSnapshot(
                            id=req_id,
                            request_raw=raw_texts[req_id],
                            cluster_id=int(cluster_label),
                            fraud_score=fraud_scores[req_id],
                            user_id=user_ids[req_id],
                        )
                    )
                clustered_count += 1

            # Eşleşmeyenleri reported olarak işaretle
            if unmatched_ids and not is_preview:
                await fr_repo.mark_reported(unmatched_ids)

            # Yeni cluster etiketlerini kaydet
            for cid, label_text in new_cluster_labels.items():
                if not is_preview:
                    new_label = FeatureClusterLabel(
                        cluster_id=cid,
                        label=label_text,
                        generated_at=datetime.now(timezone.utc),
                        report_count=0,
                    )
                    session.add(new_label)
                else:
                    preview_labels[cid] = label_text

            await session.flush()

        # ═══════════════════════════════════════════════════════════════════
        # SESSION 2 KAPANDI — Loglama ve dönüş
        # ═══════════════════════════════════════════════════════════════════

        membership_summary = {
            str(cid): {
                "count": len(ids),
                "sample_request_ids": ids[:_CLUSTER_ID_SAMPLE_LIMIT],
            }
            for cid, ids in sorted(member_map.items())
        }
        _clustering_trace(
            self.logger,
            "pipeline_assignments",
            is_preview=is_preview,
            clustered_assigned=clustered_count,
            noise_unassigned=noise_count,
            noise_sample_request_ids=noise_ids_sample,
            cluster_membership_summary=membership_summary,
            note="noise=-1 HDBSCAN gürültü; cluster_id DB/planda atanır.",
        )
        _clustering_trace(
            self.logger,
            "pipeline_groq_labels",
            is_preview=is_preview,
            clusters=groq_labels_detail,
        )
        self.logger.info(
            "Clustering pipeline tamamlandı.",
            extra={
                "clustered": clustered_count,
                "noise": noise_count,
                "new_labels": len(new_cluster_labels),
            },
        )

        # --- Kalibrasyon logu ---
        sil_score = None
        unique_cluster_list = list(set(int(lbl) for lbl in labels if lbl != -1))
        try:
            if len(unique_cluster_list) >= 2:
                from sklearn.metrics import silhouette_score

                sil_score = round(float(silhouette_score(reduced, labels)), 4)
        except Exception:
            pass

        cluster_sizes = sorted(
            [int(np.sum(labels == cid)) for cid in unique_cluster_list],
            reverse=True,
        )

        clustering_log = {
            "phase": "clustering_run_summary",
            "run_date": datetime.now(timezone.utc).isoformat(),
            "is_preview": is_preview,
            "n_sentences": len(vectors),
            "min_cluster_size": params.min_cluster_size,
            "min_samples": params.min_samples,
            "n_components_requested": params.n_components,
            "n_neighbors_requested": params.n_neighbors,
            "umap_effective_n_components": n_components_umap,
            "umap_effective_n_neighbors": n_neighbors_umap,
            "umap_init": str(umap_extra.get("init", "default")),
            "n_clusters_found": len(unique_cluster_list),
            "noise_ratio": round(noise_count / len(vectors), 4) if vectors else 0.0,
            "silhouette_score": sil_score,
            "cluster_sizes": cluster_sizes,
            "param_source": "fixed" if FIXED_CLUSTERING_PARAMS else "dynamic",
            "cluster_membership_summary": membership_summary,
            "noise_sample_request_ids": noise_ids_sample,
            "groq_labels_by_cluster": groq_labels_detail,
        }
        self.logger.info(
            "clustering_run",
            extra={"clustering": clustering_log},
        )

        unmatched_snapshots = [
            _RecordSnapshot(
                id=rid,
                request_raw=raw_texts[rid],
                fraud_score=fraud_scores[rid],
                user_id=user_ids[rid],
            )
            for rid in unmatched_ids
        ]

        return {
            "pipeline_type": "hdbscan",
            "clustered": clustered_count,
            "noise": noise_count,
            "new_labels": len(new_cluster_labels),
            "unmatched_records": unmatched_snapshots,
            "clustering_log": clustering_log,
            "preview_records": preview_records if is_preview else [],
            "preview_labels": preview_labels if is_preview else {},
        }

    async def _generate_cluster_label(
        self, cluster_id: int, sample_texts: list[str]
    ) -> str:
        """Verilen örnek talepleri kullanarak Groq'a Türkçe cluster başlığı ürettir."""
        samples_str = "\n".join(f"- {t}" for t in sample_texts)
        system_prompt = (
            "Sen bir topluluk asistanısın. Sana birbirine benzer özellik taleplerinin "
            "örneklerini vereceğim. Bu taleplerin genel temasını özetleyen, "
            "kısa (3-6 kelime), Türkçe ve açıklayıcı bir başlık üret. "
            "Sadece başlığı yaz, başka hiçbir şey yazma."
        )
        user_prompt = (
            f"Cluster #{cluster_id} için örnek talepler:\n{samples_str}\n\nBaşlık:"
        )
        try:
            return await self.groq_client.quick_ask(system_prompt, user_prompt)
        except Exception as exc:
            self.logger.warning(
                f"Label üretimi başarısız (cluster={cluster_id}): {exc}"
            )
            return f"Grup #{cluster_id}"  # Fallback label

    async def _describe_cluster(
        self, cluster_id: int, label: str, sample_texts: list[str]
    ) -> str:
        """
        Bir cluster için 1-2 cümlelik Türkçe açıklama üretir.

        _generate_cluster_label()'dan farklı olarak başlık değil,
        kısa bir niteleyici özet döndürür. Sadece bu metin LLM'e bırakılır;
        rapor yapısının geri kalanı Python'da sabit olarak kurulur.
        """
        samples_str = "\n".join(f"- {t[:150]}" for t in sample_texts[:5])
        system_prompt = (
            "Sen bir ürün analistinin asistanısın. "
            "Sana bir özellik talebi grubunun başlığı ve birkaç örnek talep verilecek. "
            "Bu grubu 1-2 cümleyle Türkçe olarak özetle. "
            "Sadece özeti yaz, başka hiçbir şey ekleme. "
            "Madde işareti, başlık veya açıklama etiketi kullanma."
        )
        user_prompt = f"Grup başlığı: {label}\nÖrnek talepler:\n{samples_str}\n\nÖzet:"
        try:
            return await self.groq_client.quick_ask(system_prompt, user_prompt)
        except Exception as exc:
            self.logger.warning(
                f"Cluster açıklaması üretilemedi (cluster={cluster_id}): {exc}"
            )
            return (
                f"Bu grupta {len(sample_texts)} benzer kullanıcı talebi bulunmaktadır."
            )

    # ==========================================================================
    # ADMIN RAPORU
    # ==========================================================================

    async def generate_admin_report(
        self,
        pipeline_result: dict | None = None,
        pipeline_stats: dict | None = None,
        is_preview: bool = False,
        preview_data: dict | None = None,
    ) -> str:
        """
        run_clustering_pipeline() sonucuna göre yapısı sabit bir Türkçe yönetici raporu üretir.

        pipeline_result içindeki "pipeline_type" anahtarına göre üç farklı rapor formatı seçilir:
          - "direct_list"          : ≤ DIRECT_DUMP_MAX_RECORDS — kayıtlar direkt listelenir.
          - "agglomerative_preview": 6-19 kayıt — ön izleme kümeleri + hafta notu.
          - "hdbscan"              : ≥ HDBSCAN_MIN_RECORDS — mevcut format + Eşleşmeyenler bölümü.

        Args:
            pipeline_result: run_clustering_pipeline()'ın döndürdüğü sözlük.
            pipeline_stats:  clustering_log dict'i (istatistikler için).

        Returns:
            Sabit yapılı Türkçe rapor metni (str).
        """
        pipeline_type = (pipeline_result or {}).get("pipeline_type", "hdbscan")

        # ── Yol 1: Direkt Listeleme (≤ DIRECT_DUMP_MAX_RECORDS) ─────────────
        if pipeline_type == "direct_list":
            direct_records = (pipeline_result or {}).get("direct_records", [])
            if not direct_records:
                return "Bu hafta raporlanacak özellik talebi bulunamadı."
            lines = [f"• {r.request_raw[:150]}" for r in direct_records]
            report = (
                f"📊 *Haftalık Özellik Talebi Raporu*\n\n"
                f"📥 Bu hafta alınan istek sayısı: *{len(direct_records)}*\n"
                f"ℹ️ Veri miktarı kümeleme için yetersiz — kayıtlar doğrudan listeleniyor:\n\n"
                + "\n".join(lines)
            )
            self.logger.info(
                "Admin raporu (direkt liste) oluşturuldu.",
                extra={"record_count": len(direct_records)},
            )
            return report

        # ── Yol 2: Agglomerative Ön İzleme (6-19 kayıt) ────────────────────
        if pipeline_type == "agglomerative_preview":
            pr_records = (pipeline_result or {}).get("preview_records", [])
            pr_labels = (pipeline_result or {}).get("preview_labels", {})
            total_n = (pipeline_result or {}).get("clustered", 0) + (
                pipeline_result or {}
            ).get("noise", 0)

            clusters_agg: dict[int, list] = {}
            for rec in pr_records:
                if rec.cluster_id is not None:
                    clusters_agg.setdefault(rec.cluster_id, []).append(rec)

            sorted_agg = sorted(
                clusters_agg.items(), key=lambda x: len(x[1]), reverse=True
            )
            medals = ["🥇", "🥈", "🥉"]
            agg_lines: list[str] = []
            for i, (cid, recs) in enumerate(sorted_agg[:3]):
                lbl = pr_labels.get(cid, f"Grup #{cid}")
                medal = medals[i] if i < 3 else "•"
                agg_lines.append(f"{medal} *{lbl}* — {len(recs)} talep")

            report = (
                f"📊 *Haftalık Özellik Talebi Raporu*\n\n"
                f"📥 Bu hafta alınan istek sayısı: *{total_n}*\n"
                f"🗂️ Ön izleme küme sayısı: *{len(clusters_agg)}*\n\n"
                + ("\n".join(agg_lines) if agg_lines else "_Küme oluşturulamadı._")
                + "\n\n⚠️ _[Ön İzleme] Yeterli veri biriktiğinde HDBSCAN ile yeniden kümelenecek._"
            )
            self.logger.info(
                "Admin raporu (agglomerative ön izleme) oluşturuldu.",
                extra={"cluster_count": len(clusters_agg), "total_n": total_n},
            )
            return report

        # ── Yol 3: HDBSCAN (≥ HDBSCAN_MIN_RECORDS) ─────────────────────────
        async with self.db.session() as session:
            fr_repo = FeatureRequestRepository(session)
            fcl_repo = FeatureClusterLabelRepository(session)
            cfg = get_settings()
            fraud_thresh = cfg.feature_request_fraud_threshold

            if is_preview and preview_data:
                clustered = preview_data.get("preview_records", [])
            else:
                clustered = await fr_repo.list_by_status("clustered")

            if not clustered:
                return "Bu hafta kümelenmiş özellik talebi bulunamadı."

            # ── Cluster bazında gruplama ──────────────────────────────────
            clusters: dict[int, list] = {}
            for record in clustered:
                if record.cluster_id is None:
                    continue
                clusters.setdefault(record.cluster_id, []).append(record)

            # ── İstatistikler ─────────────────────────────────────────────
            total_clustered = len(clustered)
            total_clusters = len(clusters)

            if pipeline_stats:
                total_embedded = pipeline_stats.get("n_sentences", total_clustered)
                noise = pipeline_stats.get("noise_ratio", 0)
                total_requests = (
                    int(total_embedded / (1 - noise)) if noise < 1 else total_embedded
                )
            else:
                total_embedded = total_clustered
                total_requests = total_clustered

            # ── Top 3 cluster (büyükten küçüğe) ──────────────────────────
            sorted_clusters = sorted(
                clusters.items(), key=lambda x: len(x[1]), reverse=True
            )
            top3 = sorted_clusters[:3]

            medals = ["🥇", "🥈", "🥉"]
            top3_lines: list[str] = []

            for i, (cid, records) in enumerate(top3):
                label = f"Grup #{cid}"
                if (
                    is_preview
                    and preview_data
                    and cid in preview_data.get("preview_labels", {})
                ):
                    label = preview_data["preview_labels"][cid]
                else:
                    label_record = await fcl_repo.get_by_cluster_id(cid)
                    if label_record:
                        label = label_record.label

                sample_texts = [r.request_raw for r in records[:5]]
                desc = await self._describe_cluster(cid, label, sample_texts)

                fraud_flagged = [
                    r for r in records if r.fraud_score and r.fraud_score > fraud_thresh
                ]
                fraud_note = (
                    f"\n   ⚠️ {len(fraud_flagged)} fraud şüpheli kayıt."
                    if fraud_flagged
                    else ""
                )

                top3_lines.append(
                    f"{medals[i]} *{label}* (ID: {cid}) — {len(records)} talep{fraud_note}\n"
                    f"   {desc}"
                )

            # ── Raporlama işlemleri ───────────────────────────────────────
            if not is_preview:
                reported_ids: list[str] = []
                for cid, records in clusters.items():
                    label_record = await fcl_repo.get_by_cluster_id(cid)
                    if label_record:
                        await fcl_repo.increment_report_count(cid)
                    for r in records:
                        reported_ids.append(r.id)

                if reported_ids:
                    await fr_repo.mark_reported(reported_ids)

            # ── Sabit şablon ──────────────────────────────────────────────
            report = (
                f"📊 *Haftalık Özellik Talebi Raporu*\n\n"
                f"📥 Bu hafta alınan istek sayısı: *{total_requests}*\n"
                f"✅ Başarılı Embedding Sayısı: *{total_embedded}*\n"
                f"🎯 Başarıyla Kümelenen İstek Sayısı: *{total_clustered}*\n"
                f"🗂️ Toplam Küme Sayısı: *{total_clusters}*\n\n"
                + "\n\n".join(top3_lines)
            )

            # ── Eşleşmeyenler bölümü ─────────────────────────────────────
            unmatched = (pipeline_result or {}).get("unmatched_records", [])
            if unmatched:
                um_lines = [f"• {r.request_raw[:150]}" for r in unmatched]
                report += (
                    "\n\n📌 *Eşleşmeyenler* _(3+ haftadır kümeye atanamayan talepler)_\n"
                    + "\n".join(um_lines)
                )

            self.logger.info(
                "Admin raporu oluşturuldu.",
                extra={
                    "total_requests": total_requests,
                    "total_clusters": total_clusters,
                    "unmatched_count": len(unmatched),
                },
            )
            return report

    async def get_cluster_details(self, cluster_id: int) -> dict[str, Any]:
        """
        Belirtilen cluster_id'ye ait tüm talepleri ve etiketleri getirir.
        """
        async with self.db.session() as session:
            fr_repo = FeatureRequestRepository(session)
            fcl_repo = FeatureClusterLabelRepository(session)

            requests = await fr_repo.list_by_cluster_id(cluster_id)
            label_record = await fcl_repo.get_by_cluster_id(cluster_id)
            label = label_record.label if label_record else f"Grup #{cluster_id}"

            return {
                "cluster_id": cluster_id,
                "label": label,
                "requests": requests,
            }

    # ==========================================================================
    # CRON YARDIMCILARI MANTIĞI
    # ==========================================================================

    async def _notify_admins(self, message: str) -> None:
        """Sistem uyarılarını slack_admins'e DM atar."""
        from packages.settings import get_settings
        from packages.slack.client import slack_client

        settings = get_settings()

        try:
            for admin_id in settings.slack_admins:
                send_notification(
                    client=slack_client.bot_client,
                    user_id=admin_id,
                    channel_id=admin_id,
                    notif_type=NotificationType.SYSTEM_ALERT,
                    text=message,
                )
        except Exception as exc:
            self.logger.error(f"Admin bildirim hatası: {exc}", exc_info=True)

    async def send_weekly_report(self) -> None:
        """Clustering pipeline'ı çalıştırır, rapor üretir, adminlere gönderir ve DB'yi temizler."""
        from packages.settings import get_settings
        from packages.slack.blocks.layouts import Layouts
        from packages.slack.client import slack_client

        try:
            cr = await self.run_clustering_pipeline()
            report_text = await self.generate_admin_report(
                pipeline_result=cr,
                pipeline_stats=cr.get("clustering_log") if cr else None,
            )
            blocks = Layouts.feature_request_report(report_text)

            settings = get_settings()
            for admin_id in settings.slack_admins:
                send_notification(
                    client=slack_client.bot_client,
                    user_id=admin_id,
                    channel_id=admin_id,
                    notif_type=NotificationType.SYSTEM_REPORT,
                    text="Haftalık Özellik Talepleri Raporu",
                    blocks=blocks,
                )

            self.logger.info("Haftalık rapor adminlere iletildi.")

            # ── Rapor başarıyla gönderildikten sonra temizlik ────────────
            # Önceki haftanın reported kayıtları ve onlara ait cluster etiketleri artık güvenle silinebilir.
            async with self.db.session() as session:
                fr_repo = FeatureRequestRepository(session)
                fcl_repo = FeatureClusterLabelRepository(session)

                deleted_reqs = await fr_repo.delete_reported()
                deleted_labels = await fcl_repo.delete_labels()

                if deleted_reqs or deleted_labels:
                    self.logger.info(
                        f"Haftalık temizlik: {deleted_reqs} reported kayıt ve {deleted_labels} cluster etiketi silindi."
                    )

        except Exception as exc:
            self.logger.error(
                f"Haftalık rapor gönderimi başarısız: {exc}", exc_info=True
            )

    async def retry_failed_embeddings(self) -> None:
        """status='embedding_failed' olan kayıtları bulup tekrar embed etmeye çalışır."""
        await self.cleanup_stale_pending_requests()
        async with self.db.session() as session:
            repo = FeatureRequestRepository(session)
            failed_records = await repo.list_by_status("embedding_failed")
            if not failed_records:
                return

            success_count = 0
            for record in failed_records:
                try:
                    vector = self.vector_client.embed(record.request_raw)
                    record.request_embedded = vector.tolist()
                    record.status = "embedded"
                    success_count += 1
                except Exception as exc:
                    self.logger.warning(f"Retry embed hatasi (ID:{record.id}): {exc}")

            await session.flush()
            self.logger.info(
                f"Embedding retry bitti: {success_count}/{len(failed_records)} kayıt kurtarıldı."
            )

    async def cleanup_stale_pending_requests(self, hours: int | None = None) -> None:
        """Belirtilen saat süresinin dışına çıkmış çürük pending_bypass kayıtlarını siler."""
        if hours is None:
            hours = get_settings().feature_request_pending_bypass_cleanup_hours
        async with self.db.session() as session:
            repo = FeatureRequestRepository(session)
            deleted_count = await repo.delete_stale_pending_bypass(hours=hours)
            if deleted_count > 0:
                self.logger.info(
                    f"Garbage collection bitti: {deleted_count} çöpe dönmüş pending_bypass silindi."
                )
            else:
                self.logger.debug(
                    "Garbage collection: Silinecek bekleyen taslak bulunamadı."
                )

    async def retry_clustering_failed(self) -> None:
        """
        status='clustering_failed' olan kayıtları bulup status'larını 'embedded' olarak sıfırlar;
        böylece bir sonraki haftalık pipeline çalıştırmasında yeniden kümeleme denenir.

        Kayıt sayısı loglanır; başarı durumunda herhangi bir bildirim gönderilmez.
        Eğer kayıt yok ise sessizce çıkar.
        """
        async with self.db.session() as session:
            repo = FeatureRequestRepository(session)
            failed_records = await repo.list_by_status("clustering_failed")
            if not failed_records:
                self.logger.debug("retry_clustering_failed: Yeniden denenecek kayıt yok.")
                return

            for record in failed_records:
                record.status = "embedded"
                record.retry_count = (record.retry_count or 0) + 1

            await session.flush()
            self.logger.info(
                f"Clustering retry: {len(failed_records)} kayıt 'embedded' statüsüne alındı."
            )

    async def check_clustering_failed(self) -> None:
        """status='clustering_failed' olan kayıtları kontrol eder ve hâlâ varsa uyarı gönderir."""
        async with self.db.session() as session:
            repo = FeatureRequestRepository(session)
            failed_records = await repo.list_by_status("clustering_failed")

            if failed_records:
                message = (
                    f"🚨 *Clustering Uyarı:* Rapor saati yaklaşmasına rağmen "
                    f"*{len(failed_records)} kayıt* hâlâ kümelenemedi (clustering_failed). "
                    f"Makine öğrenimi pipeline'ını kontrol edin."
                )
                await self._notify_admins(message)
