"""Who may do what. WORKED EXAMPLE over the scaffold's Example model: the domain stage
replaces this file with the application's own roles, personas and permissions.

Permissions are `<entity>:<action>`: read, create, update, delete for the generic data
API; a transition's name for a workflow; anything else the domain checks for itself.
`<entity>:*` is every action on the entity, `*:read` reading everything, `*` everything.
"""

ROLES = {
    "member": "Team member",
    "reviewer": "Reviewer",
    "admin": "Administrator",
}

# Offered on the sign-in screen, one click each while AUTH_PERSONAS is on.
PERSONAS = [
    {"username": "sam", "full_name": "Sam Okafor", "title": "Analyst", "team": "Operations",
     "email": "sam.okafor@example.com", "roles": ["member"]},
    {"username": "rina", "full_name": "Rina Takahashi", "title": "Team lead", "team": "Operations",
     "email": "rina.takahashi@example.com", "roles": ["reviewer"]},
    {"username": "alex", "full_name": "Alex Moreau", "title": "Platform owner", "team": "IT",
     "email": "alex.moreau@example.com", "roles": ["admin"]},
]

PERMISSIONS = {
    "member": ["example:read", "example:create", "example:update", "example:start", "example:submit"],
    "reviewer": ["example:*", "audit:read", "rules:read", "integrations:read", "users:read"],
    "admin": ["*"],
}

# Which roles see which screen (screen id -> roles). Screens not listed are for everyone.
SCREENS: dict[str, list[str]] = {}

# Which notification kinds also go out through connectors (in-app always happens).
CHANNELS = {
    "approval_requested": ["email", "teams"],
    "approval_decided": ["email"],
    "sla_breached": ["email", "slack"],
}
