"""External-service integrations.

Each subpackage owns a thin client to one external service (Obsidian
vault, n8n, Railway, GitHub, Cloudinary, V0/Vercel, SMTP). Tool wrappers
that expose service capabilities to models via function-calling live in
``openjarvis.tools.<service>_tools``; this package holds only the
transport/SDK layer.
"""
