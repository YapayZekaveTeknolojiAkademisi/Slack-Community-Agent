"""
Feature Request Repository

METODLAR
--------
  FeatureRequestRepository:
    list_by_user_this_week(user_id)       → Kullanıcının son 7 gündeki kayıtlarını getirir.
    list_by_status(status)                → Belirtilen durumdaki tüm talepleri getirir.
    list_by_cluster_id(cluster_id)        → Belirli bir cluster_id'ye sahip tüm kayıtları getirir.
    list_embedded_vectors(user_id)        → Kullanıcının son 7 gündeki gömülü (embedded) vektörleri olan taleplerini getirir.
    update_cluster(request_id, cluster_id) → Talebe cluster atar ve status'u clustered yapar.
    mark_reported(request_ids)            → Verilen taleplerin status'unu reported yapar.
    increment_retry_count(request_id)     → Noise kayıdın retry_count'unu 1 artırır.
    reset_retry_count(request_id)         → Başarılı kümeleme sonrası retry_count'u sıfırlar.
    delete_reported()                     → Reported statüsündeki tüm kayıtları kalıcı siler (hafta başı temizlik).

  FeatureClusterLabelRepository:
    get_by_cluster_id(cluster_id)         → Küme ID ile etiket nesnesini getirir.
    increment_report_count(cluster_id)    → Etiketin raporlanma sayısını bir artırır.
    delete_labels()                       → Tüm cluster etiketlerini kalıcı olarak siler.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from packages.database.models.feature_request import FeatureClusterLabel, FeatureRequest
from packages.database.repository.base import BaseRepository
from packages.settings import get_settings


class FeatureRequestRepository(BaseRepository[FeatureRequest]):
    model = FeatureRequest

    async def list_by_user_this_week(self, user_id: str) -> list[FeatureRequest]:
        """Kullanıcının rolling pencerede eklediği geçerli (kota düşen) talepleri listeler."""
        days = get_settings().feature_request_rolling_window_days
        week_ago = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(FeatureRequest)
            .where(FeatureRequest.user_id == user_id)
            .where(FeatureRequest.created_at >= week_ago)
            .where(
                FeatureRequest.status.in_(
                    ["embedded", "clustered", "reported"]
                )
            )
        )
        return list(result.scalars().all())

    async def list_by_status(self, status: str) -> list[FeatureRequest]:
        """Belirtilen statüdeki (ör. embedded, clustered vb.) tüm talepleri getirir."""
        result = await self.session.execute(
            select(FeatureRequest).where(FeatureRequest.status == status)
        )
        return list(result.scalars().all())

    async def list_by_cluster_id(self, cluster_id: int) -> list[FeatureRequest]:
        """Belirtilen cluster_id'ye sahip tüm talepleri getirir (statü bağımsız)."""
        result = await self.session.execute(
            select(FeatureRequest).where(FeatureRequest.cluster_id == cluster_id)
        )
        return list(result.scalars().all())

    async def list_embedded_vectors(self, user_id: str) -> list[FeatureRequest]:
        """
        Kullanıcının rolling pencerede eklediği ve başarılı şekilde
        vektörleştirilmiş kayıtlarını onaylanmış statülere göre listeler.
        Benzerlik (similarity) kontrolü vb. için kullanılır.
        """
        days = get_settings().feature_request_rolling_window_days
        week_ago = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.session.execute(
            select(FeatureRequest)
            .where(FeatureRequest.user_id == user_id)
            .where(FeatureRequest.created_at >= week_ago)
            .where(FeatureRequest.request_embedded.is_not(None))
            .where(FeatureRequest.status.in_(["embedded", "clustered", "reported"]))
        )
        return list(result.scalars().all())

    async def list_embedded_others_since(
        self, exclude_user_id: str, since: datetime
    ) -> list[FeatureRequest]:
        """Baskalarinin belirtilen tarihten sonraki embedded talepleri (fraud karsilastirmasi)."""
        result = await self.session.execute(
            select(FeatureRequest)
            .where(FeatureRequest.user_id != exclude_user_id)
            .where(FeatureRequest.status == "embedded")
            .where(FeatureRequest.created_at >= since)
            .where(FeatureRequest.request_embedded.is_not(None))
        )
        return list(result.scalars().all())

    async def update_cluster(
        self, request_id: str, cluster_id: int
    ) -> FeatureRequest | None:
        """
        Belirli bir talebi kümeye (cluster) atar ve statüsünü "clustered" olarak işaretler.
        """
        request = await self.get(request_id)
        if request:
            request.cluster_id = cluster_id
            request.status = "clustered"
            return await self.update(request)
        return None

    async def mark_reported(self, request_ids: list[str]) -> None:
        """
        Birden fazla kaydın statüsünü tek seferde "reported" olarak günceller.
        """
        if not request_ids:
            return

        await self.session.execute(
            update(FeatureRequest)
            .where(FeatureRequest.id.in_(request_ids))
            .values(status="reported")
        )
        await self.session.flush()

    async def increment_retry_count(self, request_id: str) -> int:
        """
        HDBSCAN noise (-1) olarak işaretlenen kaydın retry_count'unu 1 artırır.
        Güncellenen retry_count değerini döndürür.
        """
        request = await self.get(request_id)
        if request:
            request.retry_count = (request.retry_count or 0) + 1
            await self.session.flush()
            return request.retry_count
        return 0

    async def reset_retry_count(self, request_id: str) -> None:
        """
        Başarılı HDBSCAN kümelemesi sonrasında kaydın retry_count'unu sıfırlar.
        """
        request = await self.get(request_id)
        if request:
            request.retry_count = 0
            await self.session.flush()

    async def delete_reported(self) -> int:
        """
        Reported statüsündeki tüm kayıtları kalıcı olarak siler.
        Hafta başı send_weekly_report() içinde çağrılır; önceki haftanın
        raporlanmış kayıtlarını temizler.

        Returns:
            Silinen kayıt sayısı.
        """
        from sqlalchemy import delete as sql_delete

        result = await self.session.execute(
            sql_delete(FeatureRequest).where(FeatureRequest.status == "reported")
        )
        await self.session.flush()
        return result.rowcount

    async def delete_pending_bypass(self, user_id: str) -> None:
        """Kullanıcının askıda kalan pending_bypass kayıtlarını siler."""
        from sqlalchemy import delete as sql_delete

        await self.session.execute(
            sql_delete(FeatureRequest)
            .where(FeatureRequest.user_id == user_id)
            .where(FeatureRequest.status == "pending_bypass")
        )
        await self.session.flush()

    async def delete_stale_pending_bypass(self, hours: int = 24) -> int:
        """Belirtilen saatten eski olan pending_bypass kayıtlarını donanım (hard) siler."""
        from sqlalchemy import delete as sql_delete

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.session.execute(
            sql_delete(FeatureRequest)
            .where(FeatureRequest.status == "pending_bypass")
            .where(FeatureRequest.created_at < cutoff)
        )
        await self.session.flush()
        return result.rowcount


class FeatureClusterLabelRepository(BaseRepository[FeatureClusterLabel]):
    model = FeatureClusterLabel

    async def get_by_cluster_id(self, cluster_id: int) -> FeatureClusterLabel | None:
        """Belirtilen cluster_id parametresine sahip etiket nesnesini (varsa) getirir."""
        result = await self.session.execute(
            select(FeatureClusterLabel).where(
                FeatureClusterLabel.cluster_id == cluster_id
            )
        )
        return result.scalar_one_or_none()

    async def increment_report_count(
        self, cluster_id: int
    ) -> FeatureClusterLabel | None:
        """
        Zaten var olan bir küme (cluster_id) etiketinin raporlanma sayısını (report_count)
        bir (1) artırır ve güncellenmiş nesneyi döndürür.
        """
        label_record = await self.get_by_cluster_id(cluster_id)
        if label_record:
            label_record.report_count += 1
            return await self.update(label_record)
        return None

    async def list_all_cluster_ids(self) -> set[int]:
        """Tablodaki tüm cluster_id değerlerini döndürür.

        Session 1'in sonunda çağrılır; pipeline Groq çağrılarını yapmadan önce
        hangi cluster'ların zaten etiketlenmiş olduğunu öğrenmek için kullanılır.
        """
        result = await self.session.execute(
            select(FeatureClusterLabel.cluster_id)
        )
        return set(result.scalars().all())

    async def delete_labels(self) -> int:
        """
        Tüm cluster etiketlerini kalıcı olarak siler.
        Haftalık temizlik (send_weekly_report) esnasında çağrılır.
        """
        from sqlalchemy import delete as sql_delete

        result = await self.session.execute(sql_delete(FeatureClusterLabel))
        await self.session.flush()
        return result.rowcount
