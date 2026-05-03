# Examples

## Status

User:
Serena, check if WordPress is connected.

Expected:
Use `serena_wordpress_status`.

## List posts

User:
Serena, list the latest 10 posts.

Expected:
Use `serena_wordpress_list_posts`.

## Draft post

User:
Serena, create a WordPress draft titled "Insulin Resistance Basics" with this content...

Expected:
Use `serena_wordpress_create_draft` with status `draft`.

## Page

User:
Serena, create a services page for medical aid billing.

Expected:
Use `serena_wordpress_create_page` with status `draft` unless explicitly approved to publish.

## Update

User:
Serena, update post ID 123 with this revised intro.

Expected:
Ask confirmation if live content may be affected, then use `serena_wordpress_update_content`.

## Audit

User:
Serena, audit this draft for SEO and compliance.

Expected:
Use `serena_wordpress_audit_content` and provide suggestions, not direct publishing.
