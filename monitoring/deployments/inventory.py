"""Deliberately fixed inventory; never discover arbitrary host services into alerts."""
GROUPS = (
    ('smokemap', 'development', 'development', 'smokemap',
     ('frontend', 'backend', 'db', 'storage', 'media-cleanup')),
    ('smokemap', 'staging', 'quick', 'smokemap-quick-staging',
     ('frontend', 'backend', 'db', 'storage', 'media-cleanup', 'quick-app', 'quick-media')),
    ('smokemap', 'staging', 'local', 'smokemap-local-staging',
     ('edge', 'frontend', 'backend', 'db', 'storage', 'media-cleanup')),
    ('web_checker', 'production', 'production', 'web-checker-production',
     ('checker', 'maintenance')),
)
SERVICES = tuple((dict(application=a, environment=e, deployment=d, service=s), p)
                 for a, e, d, p, services in GROUPS for s in services)
WEB = dict(application='web_checker', environment='production', deployment='production')


def group(deployment):
    a, e, d, _, _ = next(g for g in GROUPS if g[2] == deployment)
    return dict(application=a, environment=e, deployment=d)
