from django.shortcuts import render
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from .serializers import RegisterSerializer, UserSerializer
from .models import CustomUser


@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request):
    """
    Register a new user (CUSTOMER or HANDICRAFTER)
    
    POST /api/register/
    {
        "name": "John Doe",
        "email": "john@example.com",
        "password": "securepass123",
        "role": "CUSTOMER" or "HANDICRAFTER"
    }
    """
    serializer = RegisterSerializer(data=request.data)
    
    if serializer.is_valid():
        user = serializer.save()
        user_data = UserSerializer(user).data
        
        # Different response messages based on role
        if user.role == 'HANDICRAFTER':
            return Response({
                'message': 'Registration successful! Your account is pending admin approval.',
                'user': user_data,
                'requires_approval': True
            }, status=status.HTTP_201_CREATED)
        else:
            return Response({
                'message': 'Registration successful! You can now log in.',
                'user': user_data,
                'requires_approval': False
            }, status=status.HTTP_201_CREATED)
    
    return Response({
        'message': 'Registration failed. Please check your input.',
        'errors': serializer.errors
    }, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    permission_classes = [AllowAny]
    
    def post(self, request):
        email = request.data.get("email")
        password = request.data.get("password")

        if not email or not password:
            return Response(
                {"message": "Email and password are required"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Authenticate using email (since USERNAME_FIELD = 'email')
        user = authenticate(request, username=email, password=password)

        if not user:
            return Response(
                {"message": "Invalid email or password"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Check if user account is active
        if not user.is_active:
            return Response(
                {"message": "Account is disabled"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Handicrafter approval check
        if user.role == "HANDICRAFTER" and not user.is_approved:
            return Response(
                {"message": "Account not approved yet"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Generate tokens
        refresh = RefreshToken.for_user(user)

        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "role": user.role,
            "is_superuser": user.is_superuser,
            "name": user.name,
            "email": user.email,
        }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pending_handicrafters(request):
    """
    Return all handicrafters who are not approved.
    Only admins can access this.
    """
    user = request.user
    if user.role != "ADMIN":
        return Response(
            {"detail": "You do not have permission to perform this action."},
            status=status.HTTP_403_FORBIDDEN
        )

    pending_users = CustomUser.objects.filter(role='HANDICRAFTER', is_approved=False)
    serializer = UserSerializer(pending_users, many=True)
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_handicrafter(request, user_id):
    user = request.user
    if user.role != "ADMIN":
        return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    try:
        handicrafter = CustomUser.objects.get(id=user_id, role="HANDICRAFTER")
        handicrafter.is_approved = True
        handicrafter.save()
        return Response({"detail": f"{handicrafter.name} approved successfully"})
    except CustomUser.DoesNotExist:
        return Response({"detail": "Handicrafter not found"}, status=status.HTTP_404_NOT_FOUND)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reject_handicrafter(request, user_id):
    user = request.user
    if user.role != "ADMIN":
        return Response({"detail": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    try:
        handicrafter = CustomUser.objects.get(id=user_id, role="HANDICRAFTER")
        handicrafter.delete()
        return Response({"detail": f"{handicrafter.name} rejected successfully"})
    except CustomUser.DoesNotExist:
        return Response({"detail": "Handicrafter not found"}, status=status.HTTP_404_NOT_FOUND)