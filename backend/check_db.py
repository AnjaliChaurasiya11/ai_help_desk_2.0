import sys
import os

# Add backend directory to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from sqlmodel import Session, create_engine
from models import LearningExample
from config import settings

engine = create_engine(settings.DATABASE_URL)
with Session(engine) as session:
    count = session.query(LearningExample).count()
    print(f"Total learning examples in database: {count}")
    if count > 0:
        examples = session.query(LearningExample).limit(5).all()
        for ex in examples:
            print(f"- {ex.raw_transcript} -> {ex.confirmed_fault_type} / {ex.confirmed_severity}")
