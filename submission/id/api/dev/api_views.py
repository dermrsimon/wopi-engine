#
# Created on Wed Nov 18 2020
#
# Copyright (c) 2020 - Simon Prast
#


from mail_templated import EmailMessage

from rest_framework import exceptions, generics, permissions, status
from rest_framework.response import Response

from submission.id.models import IDSubmission

from user.create_or_login import validated_user_data
from user.models import User

from .serializers import IDSubmissionSerializer


class HandleDocument(generics.GenericAPIView):
    queryset = IDSubmission.objects.all()
    serializer_class = IDSubmissionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self, user, latest=True):
        try:
            submission = IDSubmission.objects.get(
                submitter=user, latest=latest)
            return submission
        except IDSubmission.DoesNotExist:
            raise exceptions.NotFound

    # GET - shown own, latest ID document and verified status (customer)
    # GET - show all latest, unverified ID documents (admin)
    def get(self, request, *args, **kwargs):
        if request.user.is_staff:
            submissions = IDSubmission.objects.filter(
                verified=False, latest=True, denied=False)
            serializer = IDSubmissionSerializer(submissions, many=True)
            return Response(serializer.data)
        else:
            submission = self.get_object(user=request.user)
            serializer = IDSubmissionSerializer(submission)
            return Response(serializer.data)

    # POST - submit ID document (customer)
    def post(self, request, *args, **kwargs):
        serializer = IDSubmissionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        id_document = serializer.save(user=request.user)
        return Response({'submission_id': str(id_document)})


class VerifyDocument(generics.GenericAPIView):
    queryset = IDSubmission.objects.all()
    permission_classes = [permissions.IsAdminUser]

    def get_object(self, pk):
        try:
            submission = IDSubmission.objects.get(pk=pk)
            return submission
        except IDSubmission.DoesNotExist:
            raise exceptions.NotFound

    # PUT - set verified field value of a specific ID object (admin)
    def put(self, request, pk, *args, **kwargs):
        submission = self.get_object(pk=pk)
        if request.data.__contains__('verified'):
            if type(request.data.get('verified')) == bool:
                # Set the varified status of the id
                verified = request.data.get('verified')
                user = submission.submitter

                if submission.verified is False and verified is True:
                    mail_context = {
                        'user': user
                    }

                    mail_message = EmailMessage(
                        'mailing/verify-id-german.tpl',
                        mail_context,
                        None,
                        [user.email]
                    )

                    mail_message.send()

                submission.verified = verified
                submission.save()

                # Following lines are refreshing the user's data, in case any user keys are given
                # Ensure that the given user arguments are valid and set the values accordingly
                first_name, last_name, email, phone, password = validated_user_data(
                    request.data, change=True)

                user.first_name = first_name or user.first_name
                user.last_name = last_name or user.last_name
                user.email = email or user.email
                user.phone = phone or user.phone
                if password:
                    user.set_password(password)
                user.save()

                return Response({'success': True, 'verified': verified, 'submission': str(submission)},
                                status=status.HTTP_200_OK)
            else:
                return Response({'verified': ['Value must be a bool.']}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response(
                {'verified': ['This field is required.']}, status=status.HTTP_400_BAD_REQUEST)
        return Response({'submission_id': 'ok'})


class UserDocument(generics.GenericAPIView):
    queryset = IDSubmission.objects.all()
    serializer_class = IDSubmissionSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_user(self, pk):
        try:
            user = User.objects.get(pk=pk)
            return user
        except User.DoesNotExist:
            raise exceptions.NotFound

    # GET - all IDs of a single user (admin)
    def get(self, request, pk, *args, **kwargs):
        user = self.get_user(pk=pk)
        submissions = IDSubmission.objects.filter(submitter=user)
        serializer = IDSubmissionSerializer(submissions, many=True)
        return Response(serializer.data)
