from flask_login import UserMixin
from werkzeug.security import check_password_hash


class User(UserMixin):

    def __init__(self, username, email, password):
        self.id = username
        self.username = username
        self.email = email
        self.password = password

    def check_password(self, password_input):
        return check_password_hash(
            self.password,
            password_input
        )