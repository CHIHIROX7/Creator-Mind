import os
import secrets

os.environ.setdefault("CREATORMIND_AUTH_SECRET_KEY", secrets.token_urlsafe(48))
os.environ.setdefault("CREATORMIND_AUTH_TRUSTED_HOSTS", "localhost,127.0.0.1,testserver")
