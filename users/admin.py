from django.contrib import admin

# Register your models here.
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import CustomUser


@admin.register(CustomUser)
class CustomUserAdmin(BaseUserAdmin):
    list_display = ['email', 'name', 'role', 'is_approved', 'is_active', 'created_at']
    list_filter = ['role', 'is_approved', 'is_active', 'created_at']
    search_fields = ['email', 'name']
    ordering = ['-created_at']
    
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('name', 'role')}),
        ('Permissions', {'fields': ('is_approved', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'created_at')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'name', 'password1', 'password2', 'role', 'is_approved'),
        }),
    )
    
    readonly_fields = ['created_at', 'last_login']
    
    # Enable approval action for handicrafters
    actions = ['approve_handicrafters', 'reject_handicrafters']
    
    def approve_handicrafters(self, request, queryset):
        """Approve selected handicrafter accounts"""
        updated = queryset.filter(role='HANDICRAFTER').update(is_approved=True)
        self.message_user(request, f'{updated} handicrafter(s) approved successfully.')
    approve_handicrafters.short_description = 'Approve selected handicrafters'
    
    def reject_handicrafters(self, request, queryset):
        """Reject/unapprove selected handicrafter accounts"""
        updated = queryset.filter(role='HANDICRAFTER').update(is_approved=False)
        self.message_user(request, f'{updated} handicrafter(s) unapproved.')
    reject_handicrafters.short_description = 'Reject/Unapprove selected handicrafters'