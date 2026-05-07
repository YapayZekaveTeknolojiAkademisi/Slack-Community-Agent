from __future__ import annotations

from typing import Optional

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SystemSettings(BaseSettings):
    # Slack Ayarları
    slack_bot_token: str = Field(..., description="Slack Bot Token (xoxb-...)")
    slack_app_token: str = Field(..., description="Slack App Token (xapp-...)")
    slack_user_token: str = Field(
        ..., description="Slack User Token (xoxp-...) - Kanal oluşturma için"
    )

    slack_workspace_owner_id: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("SLACK_WORKSPACE_OWNER_ID", "slack_workspace_owner_id"),
        description="Workspace owner Slack user ID (opsiyonel)",
    )
    slack_challenge_channel: str = Field(
        ...,
        validation_alias=AliasChoices("SLACK_CHALLENGE_CHANNEL", "slack_challenge_channel"),
        description="/challenge komutlarının ana kanalı (C...)",
    )
    slack_admin_channel: str = Field(
        ...,
        validation_alias=AliasChoices("SLACK_ADMIN_CHANNEL", "slack_admin_channel"),
        description="Admin bildirim kanalı (C...)",
    )
    slack_announcement_channel: Optional[str] = Field(
        None,
        validation_alias=AliasChoices(
            "SLACK_ANNOUNCEMENT_CHANNEL", "slack_announcement_channel"
        ),
        description="Tüm etkinlik duyuruları bu kanala (C...); boşsa EVENT_CHANNEL + lokasyon kanalı",
    )
    slack_admins_csv: str = Field(
        "",
        validation_alias=AliasChoices(
            "SLACK_ADMINS",
            "SLACK_ADMIN_SLACK_ID",
            "slack_admins_csv",
        ),
        description="Virgülle ayrılmış admin Slack user ID (ilk ID tek kullanıcı bekleyen çağrılarda slack_admin_slack_id)",
    )
    slack_command_channels_raw: str = Field(
        "",
        validation_alias=AliasChoices("SLACK_COMMAND_CHANNELS", "slack_command_channels_raw"),
        description="Virgülle ayrılmış komut kanalı ID; boşsa SLACK_CHALLENGE_CHANNEL kullanılır",
    )
    slack_startup_channel: Optional[str] = Field(None, description="Slack Startup Channel ID")
    slack_report_channel: Optional[str] = Field(None, description="Slack Report Channel ID")

    monitor_challenge_interval: int = Field(
        60,
        ge=1,
        validation_alias=AliasChoices("MONITOR_CHALLENGE_INTERVAL", "monitor_challenge_interval"),
    )
    monitor_deadline_interval: int = Field(
        300,
        ge=1,
        validation_alias=AliasChoices("MONITOR_DEADLINE_INTERVAL", "monitor_deadline_interval"),
    )
    monitor_evaluation_interval: int = Field(
        600,
        ge=1,
        validation_alias=AliasChoices("MONITOR_EVALUATION_INTERVAL", "monitor_evaluation_interval"),
    )
    pending_challenge_ttl_minutes: int = Field(
        30,
        ge=1,
        validation_alias=AliasChoices(
            "PENDING_CHALLENGE_TTL_MINUTES",
            "pending_challenge_ttl_minutes",
        ),
        description="Takım kurulumu beklemede kalan geçici challenge kayıtlarının dakika cinsinden ömrü (ChallengeMonitor)",
    )

    evaluation_max_wait_hours: int = Field(
        24,
        ge=1,
        validation_alias=AliasChoices("EVALUATION_MAX_WAIT_HOURS", "evaluation_max_wait_hours"),
    )
    evaluation_jury_count: int = Field(
        2,
        ge=1,
        validation_alias=AliasChoices("EVALUATION_JURY_COUNT", "evaluation_jury_count"),
    )

    # Groq API
    groq_api_key: Optional[str] = Field(None, description="Groq Cloud API anahtarı")
    groq_model: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("GROQ_MODEL", "groq_model"),
        description="Groq chat modeli (bos birakilirsa servis varsayilanlari)",
    )

    summary_max_threads_per_channel: int = Field(
        35,
        ge=0,
        validation_alias=AliasChoices(
            "SUMMARY_MAX_THREADS_PER_CHANNEL",
            "summary_max_threads_per_channel",
        ),
        description="/channel-summary: kanal başına thread yanıtları çekilecek üst mesaj üst sınırı (0=kapalı)",
    )
    summary_max_replies_per_thread: int = Field(
        45,
        ge=1,
        le=300,
        validation_alias=AliasChoices(
            "SUMMARY_MAX_REPLIES_PER_THREAD",
            "summary_max_replies_per_thread",
        ),
        description="/channel-summary: bir thread içinde zaman penceresine düşen en fazla yanıt satırı",
    )
    summary_max_threads_all: int = Field(
        12,
        ge=0,
        validation_alias=AliasChoices(
            "SUMMARY_MAX_THREADS_ALL",
            "summary_max_threads_all",
        ),
        description="/channel-summary all: kanal başına thread üst sınırı (daha sıkı)",
    )
    summary_max_replies_per_thread_all: int = Field(
        18,
        ge=1,
        le=300,
        validation_alias=AliasChoices(
            "SUMMARY_MAX_REPLIES_PER_THREAD_ALL",
            "summary_max_replies_per_thread_all",
        ),
        description="/channel-summary all: thread başına yanıt üst sınırı",
    )
    summary_min_words_per_message: int = Field(
        2,
        ge=0,
        le=500,
        validation_alias=AliasChoices(
            "SUMMARY_MIN_WORDS_PER_MESSAGE",
            "summary_min_words_per_message",
        ),
        description="/channel-summary: boşluğa göre kelime sayısı; bu eşiğin altı LLM özeline gönderilmez (0=kapalı)",
    )
    summary_attribution_label: str = Field(
        "Özet asistanı",
        validation_alias=AliasChoices(
            "SUMMARY_ATTRIBUTION_LABEL",
            "summary_attribution_label",
        ),
        description="/channel-summary son satırında oluşturan adı (bot / ürün adı)",
    )

    # Gemini API
    gemini_api_key: Optional[str] = Field(None, description="Gemini API anahtarı")

    # Hugging Face (Model indirme / API kullanımı için)
    hf_token: Optional[str] = Field(
        None, description="Hugging Face API anahtarı (HF_TOKEN)"
    )

    # SMTP (STARTTLS; tipik olarak 587 — env → get_settings() → packages.smtp.SmtpClient)
    smtp_email: Optional[str] = Field(None, description="SMTP gönderen adresi")
    smtp_password: Optional[str] = Field(
        None, description="SMTP şifresi (Gmail için App Password önerilir)"
    )
    smtp_host: str = Field("smtp.gmail.com", description="SMTP sunucu host")
    smtp_port: int = Field(
        587, ge=1, description="SMTP port (STARTTLS için genelde 587)"
    )
    smtp_timeout: int = Field(
        10, ge=1, description="SMTP bağlantı zaman aşımı (saniye)"
    )
    admin_email: Optional[str] = Field(
        None, description="Admin e-posta adresi (virgülle ayrılmış birden fazla)"
    )

    @property
    def smtp_enabled(self) -> bool:
        """SMTP aktif mi? Hem `smtp_email` hem `smtp_password` dolu olmalı."""
        return bool(self.smtp_email) and bool(self.smtp_password)

    # Event Service Ayarlari
    event_channel: str = Field(
        ...,
        validation_alias=AliasChoices("EVENT_CHANNEL", "event_channel"),
        description="Etkinlik komut kanalı (C...)",
    )
    event_reminder_enabled: bool = Field(True, description="Hatirlatma sistemi acik/kapali")
    event_max_pending_per_user: int = Field(
        0,
        ge=0,
        validation_alias=AliasChoices(
            "EVENT_MAX_PENDING_PER_USER",
            "event_max_pending_per_user",
        ),
        description="Kullanici basina es zamanli bekleyen (pending) talep ust siniri; 0=sinirsiz",
    )
    event_approval_timeout_hours: int = Field(72, ge=1, description="Admin onay suresi (saat)")
    event_timezone: str = Field("Europe/Istanbul", description="Etkinlik saatlerinin yorumlanacagi IANA timezone (zoneinfo)")
    event_morning_reminder_hour: int = Field(8, ge=0, le=23, description="Gun basi hatirlatma saati (yerel TZ)")

    # Feature Request Service (/cemilimyapar) — kotanın zamanı UTC created_at ile (rolling pencere)
    feature_request_weekly_quota: int = Field(
        2,
        ge=1,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_WEEKLY_QUOTA", "feature_request_weekly_quota"
        ),
        description="Kullanici basina rolling penceredeki talep kotasi",
    )
    feature_request_rolling_window_days: int = Field(
        7,
        ge=1,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_ROLLING_WINDOW_DAYS",
            "feature_request_rolling_window_days",
        ),
        description="Kota, benzerlik ve fraud icin gun sayisi",
    )
    feature_request_similarity_warning: float = Field(
        0.80,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_SIMILARITY_WARNING",
            "feature_request_similarity_warning",
        ),
        description="Benzer kayit uyari esigi (cosine)",
    )
    feature_request_similarity_exact: float = Field(
        0.90,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_SIMILARITY_EXACT", "feature_request_similarity_exact"
        ),
        description="Birebir sayilacak benzerlik esigi (cosine)",
    )
    feature_request_fraud_threshold: float = Field(
        0.90,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_FRAUD_THRESHOLD", "feature_request_fraud_threshold"
        ),
        description="Fraud skoru icin benzerlik esigi",
    )
    feature_request_pending_bypass_cleanup_hours: int = Field(
        24,
        ge=1,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_PENDING_BYPASS_CLEANUP_HOURS",
            "feature_request_pending_bypass_cleanup_hours",
        ),
        description="pending_bypass taslaklarini silme esigi (saat)",
    )
    feature_request_vector_idle_interval_seconds: int = Field(
        900,
        ge=60,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_VECTOR_IDLE_INTERVAL_SECONDS",
            "feature_request_vector_idle_interval_seconds",
        ),
        description="Vector model bellekten bosaltma kontrol araligi (saniye)",
    )
    feature_request_embed_retry_hour: int = Field(
        3,
        ge=0,
        le=23,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_EMBED_RETRY_HOUR", "feature_request_embed_retry_hour"
        ),
    )
    feature_request_embed_retry_minute: int = Field(
        0,
        ge=0,
        le=59,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_EMBED_RETRY_MINUTE",
            "feature_request_embed_retry_minute",
        ),
    )
    feature_request_clustering_weekday: int = Field(
        2,
        ge=0,
        le=6,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_CLUSTERING_WEEKDAY",
            "feature_request_clustering_weekday",
        ),
        description="Kumeleme gunu (0=Pzt ... 6=Paz)",
    )
    feature_request_cluster_fail_before_pipeline_hour: int = Field(
        2,
        ge=0,
        le=23,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_CLUSTER_FAIL_BEFORE_PIPELINE_HOUR",
            "feature_request_cluster_fail_before_pipeline_hour",
        ),
    )
    feature_request_cluster_fail_before_pipeline_minute: int = Field(
        0,
        ge=0,
        le=59,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_CLUSTER_FAIL_BEFORE_PIPELINE_MINUTE",
            "feature_request_cluster_fail_before_pipeline_minute",
        ),
    )
    feature_request_clustering_hour: int = Field(
        3,
        ge=0,
        le=23,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_CLUSTERING_HOUR", "feature_request_clustering_hour"
        ),
    )
    feature_request_clustering_minute: int = Field(
        0,
        ge=0,
        le=59,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_CLUSTERING_MINUTE",
            "feature_request_clustering_minute",
        ),
    )
    feature_request_report_weekday: int = Field(
        5,
        ge=0,
        le=6,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_REPORT_WEEKDAY", "feature_request_report_weekday"
        ),
        description="Haftalik rapor gunu (0=Pzt ... 6=Paz)",
    )
    feature_request_cluster_fail_before_report_hour: int = Field(
        9,
        ge=0,
        le=23,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_CLUSTER_FAIL_BEFORE_REPORT_HOUR",
            "feature_request_cluster_fail_before_report_hour",
        ),
    )
    feature_request_cluster_fail_before_report_minute: int = Field(
        0,
        ge=0,
        le=59,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_CLUSTER_FAIL_BEFORE_REPORT_MINUTE",
            "feature_request_cluster_fail_before_report_minute",
        ),
    )
    feature_request_report_hour: int = Field(
        10,
        ge=0,
        le=23,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_REPORT_HOUR", "feature_request_report_hour"
        ),
    )
    feature_request_report_minute: int = Field(
        0,
        ge=0,
        le=59,
        validation_alias=AliasChoices(
            "FEATURE_REQUEST_REPORT_MINUTE", "feature_request_report_minute"
        ),
    )

    # Database Ayarları (POSTGRES_* veya username/password/host/port/database)
    username: str = Field(
        ...,
        validation_alias=AliasChoices("POSTGRES_USER", "username"),
        description="Veritabanı kullanıcı adı",
    )
    password: str = Field(
        ...,
        validation_alias=AliasChoices("POSTGRES_PASSWORD", "password"),
        description="Veritabanı şifresi",
    )
    host: str = Field(
        ...,
        validation_alias=AliasChoices("POSTGRES_HOST", "host"),
        description="Veritabanı host",
    )
    port: int = Field(
        ...,
        validation_alias=AliasChoices("POSTGRES_PORT", "port"),
        description="Veritabanı port",
    )
    database: str = Field(
        ...,
        validation_alias=AliasChoices("POSTGRES_DB", "database"),
        description="Veritabanı adı",
    )
    db_pool_size: int = Field(5, ge=1, description="SQLAlchemy pool boyutu")
    db_max_overflow: int = Field(10, ge=0, description="Pool overflow bağlantı sayısı")
    db_pool_timeout: int = Field(
        30, ge=1, description="Pool'dan bağlantı bekleme süresi (saniye)"
    )
    db_pool_pre_ping: bool = Field(
        True, description="Bağlantı kullanılmadan önce canlılık kontrolü"
    )
    db_pool_recycle: int = Field(
        3600, ge=60, description="Bağlantıların yenileneceği süre (saniye)"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def _parsed_slack_admins(self) -> list[str]:
        raw = (self.slack_admins_csv or "").strip()
        if not raw:
            return []
        return [x.strip() for x in raw.split(",") if x.strip()]

    @property
    def slack_admins(self) -> list[str]:
        return self._parsed_slack_admins()

    @property
    def slack_command_channels(self) -> list[str]:
        raw = (self.slack_command_channels_raw or "").strip()
        if raw:
            out = [x.strip() for x in raw.split(",") if x.strip()]
            if out:
                return out
        return [self.slack_challenge_channel]

    @property
    def slack_admin_slack_id(self) -> str:
        """Slack API'de tek kullanıcı bekleyen çağrılar için ilk admin ID."""
        admins = self._parsed_slack_admins()
        return admins[0] if admins else ""

    @model_validator(mode="after")
    def _sync_slack_admin_fields(self) -> SystemSettings:
        if not self._parsed_slack_admins():
            raise ValueError("SLACK_ADMINS tanımlanmalıdır (virgülle çoklu ID; SLACK_ADMIN_SLACK_ID eski alias).")
        return self

    @model_validator(mode="after")
    def _feature_request_similarity_order(self) -> SystemSettings:
        if self.feature_request_similarity_exact < self.feature_request_similarity_warning:
            raise ValueError(
                "FEATURE_REQUEST_SIMILARITY_EXACT, FEATURE_REQUEST_SIMILARITY_WARNING "
                "degerinden kucuk olamaz."
            )
        return self


_settings: SystemSettings | None = None


def get_settings(reload: bool = False) -> SystemSettings:
    global _settings
    if _settings is None or reload:
        _settings = SystemSettings()
    return _settings


# Geriye dönük tip / import uyumu
Settings = SystemSettings
