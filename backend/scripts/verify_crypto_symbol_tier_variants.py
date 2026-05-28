from pathlib import Path
import sys

from sqlmodel import Session, SQLModel, create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.aggressive_paper_learning_service import AggressivePaperLearningService


def main() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        svc = AggressivePaperLearningService(session)
        assert svc.symbol_tier("BTCUSD") == "MAJOR_CRYPTO"
        assert svc.symbol_tier("BTC/USD") == "MAJOR_CRYPTO"
        assert svc.symbol_tier("DOGEUSD") == "MEME_SUPPORTED"
        assert svc.symbol_tier("AAPL") == "STOCK_SUPPORTED"

    print("verify_crypto_symbol_tier_variants: PASS")


if __name__ == "__main__":
    main()
