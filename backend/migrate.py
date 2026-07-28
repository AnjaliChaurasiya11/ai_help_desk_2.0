import sys
from sqlmodel import Session
from sqlalchemy import text
from database import engine

def main():
    try:
        with Session(engine) as session:
            session.execute(text("ALTER TABLE intakes ADD COLUMN IF NOT EXISTS clarification_attempts INTEGER DEFAULT 0;"))
            session.execute(text("ALTER TABLE intakes ADD COLUMN IF NOT EXISTS status VARCHAR(30) DEFAULT 'complete';"))
            session.execute(text("ALTER TABLE intakes ADD COLUMN IF NOT EXISTS last_followup_question TEXT;"))
            session.commit()
            print("Migration successful: clarification_attempts, status, last_followup_question columns ensured.")
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
