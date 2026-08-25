from rest_framework import serializers
from .models import CustomUser


from rest_framework import serializers
from .models import CustomUser


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = CustomUser
        fields = ['name', 'email', 'password', 'role']

    def create(self, validated_data):
        role = validated_data.get('role')

        # Approval logic
        if role == "CUSTOMER":
            validated_data['is_approved'] = True
        else:
            validated_data['is_approved'] = False

        user = CustomUser.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            name=validated_data['name'],
            role=validated_data['role'],
            is_approved=validated_data['is_approved']
        )
        return user

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'name', 'email', 'role', 'is_approved']
