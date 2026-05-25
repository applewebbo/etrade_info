from django.db import models
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


class Lot(models.Model):
    ESPP = "ESPP"
    RSU = "RSU"
    LONG_TERM = "Long Term"
    SHORT_TERM = "Short Term"

    symbol = models.CharField(max_length=10)
    plan_type = models.CharField(max_length=10, choices=[(ESPP, "ESPP"), (RSU, "RSU")])
    date_acquired = models.DateField()
    sellable_qty = models.DecimalField(max_digits=10, decimal_places=4)
    cost_basis = models.DecimalField(max_digits=10, decimal_places=5)
    tax_status = models.CharField(
        max_length=20, choices=[(LONG_TERM, "Long Term"), (SHORT_TERM, "Short Term")]
    )

    class Meta:
        ordering = ["date_acquired"]

    def __str__(self):
        return f"{self.symbol} {self.plan_type} {self.date_acquired}"


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
