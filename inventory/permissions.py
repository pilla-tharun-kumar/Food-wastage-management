from rest_framework.permissions import BasePermission


class HasBusiness(BasePermission):
    message = 'Your account must belong to a business. Ask the project administrator to provision it.'

    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and hasattr(request.user, 'membership'))
