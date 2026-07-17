"""Pydantic schemas: typed shaping of request form data.

These deliberately do NOT enforce the app's business-rule validation (min
password length, "passwords must match", etc.) via Pydantic constraints —
doing so would replace today's specific, friendly flash-message errors with
Pydantic's generic validation-error format, which is a user-visible behavior
change. Schemas here just parse+strip raw form fields into a typed object;
the services layer keeps the existing validation logic and messages verbatim.
"""
