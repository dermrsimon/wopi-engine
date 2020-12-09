#
# Created on Mon Nov 02 2020
#
# Copyright (c) 2020 - Simon Prast
#


import json

from rest_framework import exceptions, generics, mixins, permissions, status
from rest_framework.response import Response

from submission.damagereport.models import DamageReport
from submission.id.models import IDSubmission
from submission.insurancesubmission.models import InsuranceSubmission

from user.authentication import refresh_token, remove_token

from user.create_or_login import create_or_login
from user.models import User

from .serializers import ChangeUserSerializer, LoginUserSerializer, RegisterUserSerializer, UserSerializer


class UserList(mixins.ListModelMixin,
               generics.GenericAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self, pk):
        try:
            user = User.objects.get(pk=pk)
            return user
        except User.DoesNotExist:
            raise exceptions.NotFound

    def get_user_submissions(self, user):
        submissions = InsuranceSubmission.objects.filter(
            submitter=user, denied=False)
        return submissions

    def get_user_id(self, user, latest=True):
        try:
            submission = IDSubmission.objects.get(
                submitter=user, latest=latest)
            return submission
        except IDSubmission.DoesNotExist:
            return False

    def get(self, request, *args, **kwargs):
        # A staff user is allowed to see all users
        if request.user.is_staff:
            return self.list(request, *args, **kwargs)
        # AnonymousUsers are denied
        # If the User is not anonymous, only show the requesting user himself
        elif not request.user.is_anonymous:
            # Create the user_dict, which initally stores the user's base data and is
            # further used to store all important data for the main profile page view.
            user_dict = {
                'id': request.user.id,
                'email': request.user.email,
                'first_name': request.user.first_name,
                'last_name': request.user.last_name,
                'phone': request.user.phone,
                'utype': request.user.utype,
                'verified': request.user.verified
            }

            # If the user is assigned an advisor, the advisor's information is added to the user_dict
            if request.user.advisor:
                # This throws an error if the advisor has no profile picture set
                # We don't care about this, as we expect every advisor to have a profile picture
                user_dict.update({
                    'advisor': {
                        'first_name': request.user.advisor.first_name,
                        'last_name': request.user.advisor.last_name,
                        'email': request.user.advisor.email,
                        'phone': request.user.advisor.phone,
                        'picture': request.user.advisor.picture.url
                    }
                })

            # Get all damage reports which were not denied by a staff member, create
            # a list and add the list as 'damagereports' to the user_dict.
            reports = DamageReport.objects.filter(
                denied=False, submitter=request.user)

            if reports.count() > 0:
                report_list = []

                for report in reports:
                    report_dict = {
                        'id': report.id,
                        'policy': {
                            'id': report.policy.id,
                            'name': str(report.policy.insurance),
                            'policy_id': report.policy.policy_id
                        },
                        'status': report.status
                    }
                    report_list.append(report_dict)

                user_dict.update({
                    'damagereports': report_list
                })

            # Get the user's identification document and show its attributes at the user_dict
            doc = self.get_user_id(user=request.user)
            if doc:
                doc_dict = {
                    'url': doc.document.url,
                    'verified': doc.verified,
                    'denied': doc.denied
                }

                user_dict.update({
                    'id_document': doc_dict
                })

            # If the user has any insurance submissions, create a list containing
            # all submissions and add the list as 'insurances' to the user_dict.
            insurance_submissions = self.get_user_submissions(
                user=request.user)

            if insurance_submissions.count() > 0:
                submission_list = []

                # Every submission's data is saved to a dictionary and appended to the submission data list
                for submission in insurance_submissions:
                    submission_dict = {
                        'id': submission.id,
                        'insurance': str(submission.insurance),
                        'policy_id': submission.policy_id,
                        'submitter': str(submission.submitter),
                        'status': {
                            'active': submission.active
                        },
                        'data': json.loads((submission.data).replace("\'", "\""))
                    }
                    submission_list.append(submission_dict)

                user_dict.update({
                    'insurances': submission_list
                })

            return Response(user_dict, status=status.HTTP_200_OK)
        else:
            exceptions.PermissionDenied


class UserCreateOrLogin(generics.GenericAPIView):
    serializer_class = RegisterUserSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        if not request.user.is_anonymous:
            # Deny any request thats not from an AnonymousUser
            return Response(
                {'detail': 'You cannot create an account while authenticated.'},
                status=status.HTTP_403_FORBIDDEN
            )
        else:
            serializer = RegisterUserSerializer(data=request.data)
            logSerializer = LoginUserSerializer(data=request.data)
            # Create and authenticate the user, in case the given request data is valid
            return_dict, auth_status, user = create_or_login(
                serializer, logSerializer, request)
            return Response(return_dict, status=auth_status)


class UserDetail(mixins.RetrieveModelMixin,
                 mixins.UpdateModelMixin,
                 mixins.DestroyModelMixin,
                 generics.GenericAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def check_requested_object(self, pk):
        try:
            user = User.objects.get(pk=pk)
            return user
        except User.DoesNotExist:
            raise exceptions.NotFound

    def get(self, request, pk, *args, **kwargs):
        # Get the requested user
        requested_user = self.check_requested_object(pk=pk)
        # Only allow staff users and own requests
        if request.user.is_staff or requested_user == request.user:
            return self.retrieve(request, *args, **kwargs)
        else:
            raise exceptions.PermissionDenied

    def put(self, request, pk, *args, **kwargs):
        # Get the requested user
        requested_user = self.check_requested_object(pk=pk)
        # Only allow staff users and own requests
        if request.user.is_staff or requested_user == request.user:
            # This copies the request.data dictionary,
            # as request.data is read-only.
            altered_request_data = request.data.copy()

            # last_login cannot be altered.
            if altered_request_data.__contains__('last_login'):
                altered_request_data.pop('last_login')

            # utype can only be altered by administrative accounts.
            if altered_request_data.__contains__('utype') and not request.user.is_staff:
                altered_request_data.pop('utype')

            # Update the object using the serializer.
            partial = kwargs.pop('partial', False)
            instance = self.get_object()
            serializer = ChangeUserSerializer(
                instance, data=altered_request_data, partial=partial)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)

            # Copy the read-only serializer.data dictionary.
            serializer_data = serializer.data

            # Set a new password if it was sent through the request body
            password = request.data.get('password', False)
            if password:
                requested_user.set_password(password)
                requested_user.save()

                # If the user who requests the password change is the user itself,
                # the user is given a new token. If the password is changed by an admin,
                # the valid login token is deleted.
                if requested_user == request.user:
                    token = refresh_token(requested_user)
                    serializer_data.update({'token': str(token)})
                else:
                    remove_token(requested_user)

            return Response(serializer_data)
        else:
            raise exceptions.PermissionDenied
