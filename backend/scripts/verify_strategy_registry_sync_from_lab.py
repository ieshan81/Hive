import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlmodel import Session, select
from app.database import StrategyRegistry, engine, init_db
from app.services.strategy_registry_service import StrategyRegistryService

def main():
    init_db()
    with Session(engine) as s:
        StrategyRegistryService(s).sync_from_lab()
        s.commit()
        assert len(s.exec(select(StrategyRegistry)).all()) >= 5
    print("verify_strategy_registry_sync_from_lab: OK")

if __name__ == "__main__":
    main()
