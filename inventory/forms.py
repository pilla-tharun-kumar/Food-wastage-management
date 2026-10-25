from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model


class SignupForm(UserCreationForm):
    business_name = forms.CharField(max_length=160, label='Business or workspace name')
    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ('username', 'email', 'business_name', 'password1', 'password2')

    def clean_business_name(self):
        value = self.cleaned_data['business_name'].strip()
        if not value:
            raise forms.ValidationError('Enter a workspace name.')
        return value
