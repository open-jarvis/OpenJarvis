---
name: serena-wordpress
description: wordpress website building and content management for Serena. Use when the user asks Serena to manage Dr Piet or Serena WordPress sites, create posts or pages, build landing pages, create published website content, manage media, inspect/search site content, plan website structures, audit SEO, or prepare WordPress content for approval. Supports multiple sites such as drpiet and serena. Requires explicit approval before publishing, updating live public content, deleting content, uploading public media, or changing settings.
---

# Serena WordPress Website Builder

Use this skill when Serena needs to work with WordPress sites through natural language.

## Supported sites

Serena supports multi-site WordPress configuration using:

- `WORDPRESS_DEFAULT_SITE`
- `WORDPRESS_SITES`
- `WORDPRESS_SITE_<SITEKEY>_...`

Current intended site keys:

- `drpiet`
- `serena`

Default site:

- `drpiet`

## Natural language examples

- "Serena, check WordPress status for Dr Piet."
- "Serena, check WordPress status for the Serena website."
- "List the latest WordPress posts on drpiet."
- "Create a WordPress draft about insulin resistance."
- "Create a landing page for medical aid billing services."
- "Build a services page for Dr Piet but keep it as a draft."
- "Prepare a published page, but ask me before publishing."
- "Update post ID 123 with this revised content after I approve."
- "Search the Dr Piet website for posts about diabetes."
- "Audit this WordPress draft for SEO and healthcare compliance."

## Native tools

Use native Python tools in `src/openjarvis/tools/serena_wordpress.py` for reliable write actions:

- `serena_wordpress_status`
- `serena_wordpress_list_posts`
- `serena_wordpress_list_pages`
- `serena_wordpress_create_draft`
- `serena_wordpress_create_page`
- `serena_wordpress_update_content`
- `serena_wordpress_search`
- `serena_wordpress_upload_media`
- `serena_wordpress_audit_content`

## MCP policy

If WordPress MCP is configured:

Prefer MCP for:

- search
- summaries
- content planning
- site mapping
- broader site inspection

Prefer native Python REST tools for:

- create
- update
- publish
- delete
- media upload

Do not use MCP for risky write actions unless the user explicitly approves and the MCP action is verified.

## Approval rules

Always ask for explicit approval before:

- publishing a post or page
- updating live public content
- deleting content
- uploading public media
- changing menus, plugins, themes, users, or site settings
- making medical or clinical claims on a public page
- changing SEO metadata for live pages

Draft creation is allowed when credentials are configured, but Serena must summarize what she created.

## Website-builder behavior

When building a page, Serena should prepare:

- page title
- slug
- section structure
- hero section
- call-to-action
- body copy
- FAQ section where useful
- SEO title
- meta description
- internal-link suggestions
- compliance review notes for healthcare content

Default to draft unless the user explicitly approves publishing.

## Safety for healthcare content

For Dr Piet content:

- Do not make unsupported clinical claims.
- Do not imply guaranteed outcomes.
- Recommend clinician review before publishing.
- Prefer education and compliance-safe language.
- Include appropriate disclaimers when needed.
