from django.urls import path
from .views import register_user, LoginView, pending_handicrafters, approve_handicrafter, reject_handicrafter
from . import views

urlpatterns = [
    path('register/', register_user, name='register'),
    path("login/", LoginView.as_view(), name="login"),
    path('pending-handicrafters/', pending_handicrafters, name='pending-handicrafters'),
    path('approve-handicrafter/<int:user_id>/', views.approve_handicrafter),
    path('reject-handicrafter/<int:user_id>/', views.reject_handicrafter),
]