#
# Created on Mon Nov 02 2020
#
# Copyright (c) 2020 - Simon Prast
#


import json

from datetime import datetime, timezone

from django.core.mail import send_mail

from rest_framework import exceptions, generics, mixins, permissions, status
from rest_framework.response import Response

from submission.damagereport.models import DamageReport
from submission.id.models import IDSubmission
from submission.insurancesubmission.models import InsuranceSubmission

from user.authentication import refresh_token, remove_token

from user.create_or_login import create_or_login, validated_user_data
from user.models import ResetPasswordToken, User, VerifyEmailToken

from .serializers import ChangeUserSerializer, LoginUserSerializer, UserSerializer, UserDetailSerializer


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

    def get(self, request, *args, **kwargs):
        # A staff user is allowed to see all users
        if request.user.is_staff:
            staff_members = User.objects.filter(utype=7)
            customers = User.objects.filter(utype=1)

            user_list = [create_user_dict(request.user)]

            staff_list = []
            for staff in staff_members:
                staff_list.append(create_basic_user_dict(staff))

            customer_list = []
            for customer in customers:
                customer_list.append(create_basic_user_dict(customer))

            user_list.append(staff_list)
            user_list.append(customer_list)

            return Response(user_list, status=status.HTTP_200_OK)
        # AnonymousUsers are denied
        # If the User is not anonymous, only show the requesting user himself
        elif not request.user.is_anonymous:
            user_dict = create_user_dict(request.user)
            return Response(user_dict, status=status.HTTP_200_OK)
        else:
            exceptions.PermissionDenied


class UserCreateOrLogin(generics.GenericAPIView):
    serializer_class = UserDetailSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        if not request.user.is_anonymous:
            # Deny any request thats not from an AnonymousUser
            return Response(
                {'detail': 'You cannot create an account while authenticated.'},
                status=status.HTTP_403_FORBIDDEN
            )
        else:
            serializer = UserDetailSerializer(data=request.data)
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
    serializer_class = ChangeUserSerializer
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
            user_dict = create_user_dict(requested_user)
            return Response(user_dict, status=status.HTTP_200_OK)
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

            if requested_user == request.user:
                if not request.data.__contains__('current_password'):
                    return Response({'current_password': ['This field is required.']})

                if not request.user.check_password(request.data.get('current_password')):
                    return Response({'current_password_does_not_match': ['Given password is wrong.']})

            # Update the object using the serializer.
            partial = kwargs.pop('partial', False)
            instance = requested_user
            serializer = self.get_serializer(
                instance, data=altered_request_data, partial=partial)
            serializer.is_valid(raise_exception=True)
            user, new_password = serializer.update(
                instance, serializer.validated_data)

            if user == "AdvisorDoesNotExist":
                return Response({'advisor_does_not_exist': 'No advisor with given UUID found.'},
                                status=status.HTTP_400_BAD_REQUEST)

            # Copy the read-only serializer.data dictionary.
            serializer_data = serializer.data

            # If the password was refreshed, handle the user's current token
            if new_password:
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


def create_basic_user_dict(user):
    # Create the user_dict, which initally stores the user's base data and is
    # further used to store all important data for the main profile page view.
    user_dict = {
        'id': user.id,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'phone': user.phone,
        'utype': user.utype,
        'verified': user.verified
    }

    if user.is_staff:
        user_dict.update({
            'picture': user.picture.url
        })

    # If the user is assigned an advisor, the advisor's information is added to the user_dict
    if user.advisor:
        # This throws an error if the advisor has no profile picture set
        # We don't care about this, as we expect every advisor to have a profile picture
        user_dict.update({
            'advisor': {
                'first_name': user.advisor.first_name,
                'last_name': user.advisor.last_name,
                'email': user.advisor.email,
                'phone': user.advisor.phone,
                'picture': user.advisor.picture.url
            }
        })

    # Get basic information about waiting requests of this specific user
    reports = DamageReport.objects.filter(submitter=user, status='w')

    if reports.count() > 0:
        report_list = []

        for report in reports:
            report_dict = {
                'id': report.id
            }
            report_list.append(report_dict)

        user_dict.update({
            'damagereports': report_list
        })

    # Get the user's identification document and show its attributes at the user_dict
    doc = get_user_id(user=user)
    if doc:
        doc_dict = {
            'id': doc.id,
            'verified': doc.verified
        }

        user_dict.update({
            'id_document': doc_dict
        })

    # If the user has any unanswered insurance submissions, create a list containing
    # all unanswered submissions and add the list as 'insurances' to the user_dict.
    insurance_submissions = get_user_submissions(
        user=user, active=False)

    if insurance_submissions.count() > 0:
        submission_list = []

        # Every submission's data is saved to a dictionary and appended to the submission data list
        for submission in insurance_submissions:
            submission_dict = {
                'id': submission.id
            }
            submission_list.append(submission_dict)

        user_dict.update({
            'insurances': submission_list
        })

    return user_dict


def create_user_dict(user):
    # Create the user_dict, which initally stores the user's base data and is
    # further used to store all important data for the main profile page view.
    user_dict = {
        'id': user.id,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'phone': user.phone,
        'address1': user.address_1,
        'address2': user.address_2,
        'zipcode': user.zipcode,
        'utype': user.utype,
        'verified': user.verified
    }

    # If the user is assigned an advisor, the advisor's information is added to the user_dict
    if user.advisor:
        # This throws an error if the advisor has no profile picture set
        # We don't care about this, as we expect every advisor to have a profile picture
        user_dict.update({
            'advisor': {
                'first_name': user.advisor.first_name,
                'last_name': user.advisor.last_name,
                'email': user.advisor.email,
                'phone': user.advisor.phone,
                'picture': user.advisor.picture.url
            }
        })

    # Get all damage reports which were not denied by a staff member, create
    # a list and add the list as 'damagereports' to the user_dict.
    reports = DamageReport.objects.filter(
        denied=False, submitter=user)

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
    doc = get_user_id(user=user)
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
    insurance_submissions = get_user_submissions(
        user=user)

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

    return user_dict


def get_user_id(user, latest=True):
    try:
        submission = IDSubmission.objects.get(
            submitter=user, latest=latest)
        return submission
    except IDSubmission.DoesNotExist:
        return False


def get_user_submissions(user, active=None):
    if active is not None:
        submissions = InsuranceSubmission.objects.filter(
            submitter=user, denied=False, active=active
        )
    else:
        submissions = InsuranceSubmission.objects.filter(
            submitter=user, denied=False
        )
    return submissions


class VerifyEmail(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def get_token_obj(self, token):
        token_objs = VerifyEmailToken.objects.filter(token=token)

        if token_objs.count() > 0:
            token_obj = VerifyEmailToken.objects.get(token=token)

            if (datetime.now(timezone.utc) - token_obj.created_at).total_seconds() > 7200:
                token_obj.delete()
                return 'TokenExpired'

            return token_obj
        else:
            return None

    def post(self, request, token, *args, **kwargs):
        if request.user.is_anonymous:
            # Deny any request thats not from an AnonymousUser
            return Response(
                {'PermissionDenied': 'You must be authenticated in order to verify your email address.'},
                status=status.HTTP_403_FORBIDDEN
            )

        token_obj = self.get_token_obj(token)

        if token_obj is None:
            return Response(
                {'TokenNotFound': 'Given token was not found.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if token_obj == 'TokenExpired':
            return Response(
                {'TokenExpired': 'This token is expired.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if token_obj.user != request.user:
            return Response(
                {'PermissionDenied': 'This token is not for this user.'},
                status=status.HTTP_403_FORBIDDEN
            )

        token_obj.user.verified = True
        token_obj.user.save()
        token_obj.delete()

        return Response(
            {'success': 'The user is now verified.'},
            status=status.HTTP_200_OK
        )


class RequestEmailVerification(generics.GenericAPIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, *args, **kwargs):
        if request.user.is_anonymous:
            # Deny any request thats not from an AnonymousUser
            return Response(
                {'PermissionDenied': 'You must be authenticated in order to verify your email address.'},
                status=status.HTTP_403_FORBIDDEN
            )

        current_tokens = VerifyEmailToken.objects.filter(user=request.user)

        if current_tokens.count() > 0:
            token_obj = VerifyEmailToken.objects.get(user=request.user)

            if (datetime.now(timezone.utc) - token_obj.created_at).total_seconds() < 7200:
                return Response(
                    {'VerificationAlreadyActive':
                        'The verification process for this email is already initiated (less than 2h ago).'},
                    status=status.HTTP_403_FORBIDDEN
                )
            else:
                token_obj.delete()

        verify_email_token = VerifyEmailToken(user=request.user)
        verify_email_token.save()

        mail_message = \
            'Hallo ' + request.user.first_name + '!' \
            '<br><br>Hier ist die Mail zum Bestätigen deiner E-Mail Adresse.' \
            '<br><br>Um deine E-Mail Adresse zu bestätigen, klick bitte auf folgenden Link:' \
            '<br><a href="https://app.spardaplus.at/v?token=' + str(verify_email_token.token) + \
            '">https://app.spardaplus.at/v?token=' + \
            str(verify_email_token.token) + '</a>'

        send_mail(
            'Bestätigung Deiner E-Mail Adresse',
            mail_message,
            None,
            [request.user.email],
            fail_silently=False,
            html_message=mail_message
        )

        return Response(
            {'success': 'E-Mail was sent to the user.'},
            status=status.HTTP_200_OK
        )


class ResetPassword(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]

    def get_token_obj(self, token):
        token_objs = ResetPasswordToken.objects.filter(token=token)

        if token_objs.count() > 0:
            token_obj = ResetPasswordToken.objects.get(token=token)

            if (datetime.now(timezone.utc) - token_obj.created_at).total_seconds() > 7200:
                token_obj.delete()
                return 'TokenExpired'

            return token_obj
        else:
            return None

    def post(self, request, token, *args, **kwargs):
        if not request.user.is_anonymous:
            # Deny any request thats not from an AnonymousUser
            return Response(
                {'PermissionDenied': 'You cannot use this while authenticated.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if not request.data.__contains__('password'):
            return Response(
                {'password': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST
            )

        token_obj = self.get_token_obj(token)

        if token_obj is None:
            return Response(
                {'TokenNotFound': 'Given token was not found.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if token_obj == 'TokenExpired':
            return Response(
                {'TokenExpired': 'This token is expired.'},
                status=status.HTTP_403_FORBIDDEN
            )

        first_name, last_name, email, phone, new_password = validated_user_data(
            request.data, change=True)

        token_obj.user.set_password(new_password)

        remove_token(token_obj.user)

        token_obj.user.save()
        token_obj.delete()

        return Response(
            {'success': 'The user\'s new password is now active.'},
            status=status.HTTP_200_OK
        )


class RequestPasswordReset(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]

    def get_user(self, email):
        users = User.objects.filter(email=email)

        if users.count() > 0:
            user = User.objects.get(email=email)
            return user
        else:
            return None

    def post(self, request, *args, **kwargs):
        if not request.user.is_anonymous:
            # Deny any request thats not from an AnonymousUser
            return Response(
                {'PermissionDenied': 'You cannot use this while authenticated.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if not request.data.__contains__('email'):
            return Response(
                {'email': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST
            )

        email = request.data.get('email')

        user = self.get_user(email)

        if user is None:
            return Response(
                {'UserDoesNotExist': 'No user found with given email.'}, status=status.HTTP_400_BAD_REQUEST
            )

        current_tokens = ResetPasswordToken.objects.filter(user=user)

        if current_tokens.count() > 0:
            token_obj = ResetPasswordToken.objects.get(user=user)

            if (datetime.now(timezone.utc) - token_obj.created_at).total_seconds() < 900:
                return Response(
                    {'PasswordResetAlreadyActive':
                        'The password reset process for this user is already initiated (less than 15 min ago).'},
                    status=status.HTTP_403_FORBIDDEN
                )
            else:
                token_obj.delete()

        reset_password_token = ResetPasswordToken(user=user)
        reset_password_token.save()

        mail_message = \
            'Hallo ' + user.first_name + '!' \
            '<br><br>Wir haben eine Anfrage erhalten, Dein Passwort für das SPARDA-Kundenportal zurückzusetzen.' \
            '<br><br>Unter diesem Link kannst Du ein neues Passwort festlegen:' \
            '<br><a href="https://app.spardaplus.at/v?token=' + str(reset_password_token.token) + \
            '">https://app.spardaplus.at/v?token=' + str(reset_password_token.token) + '</a>' \
            '<br><br>Mit freundlichen Grüßen<br>Dein SPARDA Team'

        send_mail(
            'Zurücksetzen deines SPARDA-Passworts',
            mail_message,
            None,
            [user.email],
            fail_silently=False,
            html_message=mail_message
        )

        return Response(
            {'success': 'E-Mail was sent to the user.'},
            status=status.HTTP_200_OK
        )
