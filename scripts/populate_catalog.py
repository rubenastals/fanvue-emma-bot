# scripts/populate_catalog.py
from database.db_manager import DBManager
from database.models import ContentCatalog
from utils.embedding_utils import generate_embedding, build_content_embedding_text

db = DBManager()
session = db.get_session()

# Example content entry
title = "Emma's Hot Tease"
description = "A 5-minute video of me playing with myself, moaning your name."
tags = ["hardcore", "solo", "tease"]

content = ContentCatalog(
    title=title,
    description=description,
    file_url="https://storage.fanvue.com/emma_hot_tease.mp4",
    price_base=14.99,
    price_whale=29.99,
    duration_seconds=300,
    type="video",
    tags=tags,
    explicitness_score=9,
    softness_score=3,
    embedding=generate_embedding(build_content_embedding_text(title, description, tags))
)
session.add(content)
session.commit()
print("✅ Content catalog populated!")

# Add at least 10-20 videos, photos, and audio files for variety.
