from django.conf import settings
from django.core.mail import send_mail

from .models import VerificationCode


PURPOSE_TEXT = {
    VerificationCode.Purpose.ACCOUNT_RECOVERY: '找回造物者用户名',
    VerificationCode.Purpose.PASSWORD_RESET: '重置造物者密码',
}


def send_email_code(destination, purpose, code):
    action = PURPOSE_TEXT[purpose]
    send_mail(
        f'造物者验证码：{action}',
        (
            f'你的验证码是：{code}\n\n'
            f'该验证码用于{action}，{settings.VERIFICATION_CODE_EXPIRE_MINUTES}分钟内有效。\n'
            '如果不是你本人操作，请忽略此邮件。'
        ),
        settings.DEFAULT_FROM_EMAIL,
        [destination],
        fail_silently=False,
    )


def deliver_code(channel, destination, purpose, code):
    send_email_code(destination, purpose, code)
