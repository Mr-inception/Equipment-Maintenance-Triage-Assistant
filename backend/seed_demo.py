"""Load demo reports (no AI call). Run from backend/ with the venv active:  python seed_demo.py
Safe to run more than once."""
from app.database import init_db
from app.demo import seed_demo_data


def main() -> None:
    init_db()
    created = seed_demo_data()
    if not created:
        print("Demo data already present; nothing to do.")
        return
    for rid, etype, ident in created:
        print(f"Created report #{rid} for {etype} {ident}")


if __name__ == "__main__":
    main()