from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column


from app.db import Base


class AppSettings(Base):
    __tablename__ = "app_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_app_settings_singleton"),
        CheckConstraint("llm_provider IN ('ollama','anthropic')", name="ck_app_settings_provider"),
        CheckConstraint("default_rag_top_k > 0", name="ck_app_settings_default_rag_top_k"),
        CheckConstraint(
            "default_rag_similarity_floor >= 0 AND default_rag_similarity_floor <= 1",
            name="ck_app_settings_default_rag_similarity_floor",
        ),
        CheckConstraint("num_ctx > 0", name="ck_app_settings_num_ctx"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    app_name: Mapped[str | None] = mapped_column(String(255))
    llm_provider: Mapped[str] = mapped_column(String(20), nullable=False, server_default="ollama")
    ollama_chat_model: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default="qwen2.5:14b-instruct-q4_K_M"
    )
    # Small/fast local model used only for the keyword graph's "Generate All"
    # basic-summary batch job (app.jobs.generate_graph_summaries) -- always
    # Ollama regardless of llm_provider, since that job explicitly favors
    # speed over quality across many sequential summaries. NULL disables the
    # "Generate All" button client-side rather than silently falling back to
    # the (slower) main chat model.
    ollama_fast_model: Mapped[str | None] = mapped_column(String(128))
    anthropic_chat_model: Mapped[str] = mapped_column(
        String(128), nullable=False, server_default="claude-sonnet-4-5"
    )
    anthropic_api_key: Mapped[str | None] = mapped_column(String(255))
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False, server_default="nomic-embed-text")
    # Captioning saved diagrams (app.jobs.process_diagrams) always goes
    # through a local Ollama vision model, regardless of llm_provider --
    # NULL means "not configured yet", in which case diagrams are still saved
    # with OCR text only, no caption, rather than hard-failing.
    ollama_vision_model: Mapped[str | None] = mapped_column(String(128))
    whisper_model: Mapped[str] = mapped_column(String(32), nullable=False, server_default="small")
    whisper_idle_unload_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="300")
    # Chat retrieval defaults -- how many note excerpts get pulled into context
    # per question, and how relevant (cosine similarity) one has to be to
    # qualify at all. Projects can override either via Project.rag_top_k /
    # rag_similarity_floor; these are the fallback when a project doesn't.
    default_rag_top_k: Mapped[int] = mapped_column(Integer, nullable=False, server_default="6")
    default_rag_similarity_floor: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.35")
    # Ollama's own hardcoded default when no `options.num_ctx` is passed is
    # only 2048 tokens, which silently truncates the RAG context block plus
    # chat history on anything but trivial exchanges -- see OllamaProvider.chat().
    # 8192 is a middle ground: qwen2.5:14b-instruct-q4_K_M supports up to
    # 32768, and 8192 comfortably fits a top_k=6-8 context block plus several
    # turns of history at a KV-cache cost of roughly 1-1.5GB extra VRAM over
    # the 2048 default at this model size -- revisit downward if a low-VRAM
    # host struggles, or upward if answers still seem to miss early context on
    # long chat sessions.
    num_ctx: Mapped[int] = mapped_column(Integer, nullable=False, server_default="8192")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
