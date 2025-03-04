from django.contrib import admin
from .models import Account, AccountType, AccountStatusHistory

# Register your models here.
@admin.register(AccountType)
class AccountTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'normal_balance', 'description')
    search_fields = ('name',)

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('number', 'name', 'account_type', 'status', 'is_active')
    list_filter = ('account_type', 'status', 'is_active')
    search_fields = ('number', 'name', 'description')
    readonly_fields = ('is_active', 'created_at', 'updated_at')

@admin.register(AccountStatusHistory)
class AccountStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('account', 'status', 'effective_date', 'created_at')
    list_filter = ('status',)
    search_fields = ('account__number', 'account__name', 'notes')
    date_hierarchy = 'effective_date'
