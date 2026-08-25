from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser,
    PermissionsMixin,
    BaseUserManager
)


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "ADMIN")
        extra_fields.setdefault("is_approved", True)

        return self.create_user(email, password, **extra_fields)
    

class CustomUser(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = (
        ('ADMIN', 'Admin'),
        ('HANDICRAFTER', 'Handicrafter'),
        ('CUSTOMER', 'Customer'),
    )

    id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=50, choices=ROLE_CHOICES)
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    def __str__(self):
        return self.email
