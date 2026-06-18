"""Platform connection management — encrypt/store and load tenant sessions.

To be implemented in the platforms slice. Functions take `session` first and
are scoped by `tenant_id`. Uses app.utils.encryption for the session blob.
"""
