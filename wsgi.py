import os

from app import app, db, PRODUCTION


# Ensure tables exist in environments where migrations aren't set up.
# In production you'd typically use Alembic migrations instead.
with app.app_context():
    default_create = "0" if PRODUCTION else "1"
    if os.environ.get("LINKUP_CREATE_TABLES", default_create) == "1":
        db.create_all()
