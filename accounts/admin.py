# from django.contrib import admin
# from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
# from .models import User, PasswordResetToken

# @admin.register(User)
# class UserAdmin(BaseUserAdmin):
#     list_display = ('email', 'full_name', 'is_staff', 'is_active', 'date_joined')
#     list_filter = ('is_staff', 'is_active', 'date_joined')
#     search_fields = ('email', 'full_name')
#     ordering = ('-date_joined',)
    
#     fieldsets = (
#         (None, {'fields': ('email', 'password')}),
#         ('Personal Info', {'fields': ('full_name', 'phone')}),
#         ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
#         ('Important dates', {'fields': ('last_login', 'date_joined')}),
#     )
    
#     add_fieldsets = (
#         (None, {
#             'classes': ('wide',),
#             'fields': ('email', 'full_name', 'password1', 'password2'),
#         }),
#     )

# @admin.register(PasswordResetToken)
# class PasswordResetTokenAdmin(admin.ModelAdmin):
#     list_display = ('user', 'token', 'created_at', 'used')
#     list_filter = ('used', 'created_at')
#     search_fields = ('user__email', 'token')