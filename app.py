from nanodjango import Django

app = Django(
    DATABASES={
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": "db.sqlite3",
        }
    },
    SECRET_KEY="local-dev-only-not-for-production",  # nosec B106
    ALLOWED_HOSTS=["localhost", "127.0.0.1"],
    INSTALLED_APPS=[
        "django.contrib.contenttypes",
        "django.contrib.auth",
        "django.contrib.staticfiles",
    ],
    STATIC_URL="/static/",
    STATICFILES_DIRS=["static"],
    TEMPLATES=[
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": ["templates"],
            "APP_DIRS": False,
            "OPTIONS": {
                "context_processors": [
                    "django.template.context_processors.request",
                ]
            },
        }
    ],
)


@app.route("/")
def dashboard(request):
    from django.shortcuts import render

    return render(request, "dashboard.html", {})


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] != "run":
        app.manage(sys.argv[1:])
    else:
        app.run()
