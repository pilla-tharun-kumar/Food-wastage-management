from django.contrib import admin
from .models import Business, Category, Membership

# Stock writes use the audited API only. Django admin is for trusted project administrators.
admin.site.register([Business, Membership, Category])
