import re
from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, join_room, leave_room
from flask_login import LoginManager, current_user, login_required, login_user, logout_user

from db import (
    add_room_members,
    get_messages,
    get_room,
    get_room_members,
    get_rooms_for_user,
    get_user,
    is_room_admin,
    is_room_member,
    remove_room_members,
    save_message,
    save_room,
    save_user,
    update_room
)

import pymongo.errors
from datetime import datetime
from bson.json_util import dumps

app = Flask(__name__)
app.secret_key = "my_secret_key"
app.config['TEMPLATES_AUTO_RELOAD'] = True  
app.jinja_env.auto_reload = True 
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.template_filter('str')
def str_filter(value):
    return str(value)



socketio = SocketIO(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)


@login_manager.user_loader
def load_user(username):
    return get_user(username)


@app.route('/home')
@login_required
def home():
    rooms = get_rooms_for_user(current_user.username)
    for room in rooms:
        room['room_id_str'] = str(room['_id']['room_id'])
    return render_template("index.html", rooms=rooms)


@app.route('/', methods=['GET', 'POST'])
def login():

    if current_user.is_authenticated:
        return redirect(url_for('home'))

    message = ""

    if request.method == "POST":

        username = request.form.get('username')
        password = request.form.get('password')

        user = get_user(username)

        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('home'))

        message = "Invalid username or password"

    return render_template('login.html', message=message)


@app.route('/signup', methods=['GET', 'POST'])
def signup():

    if current_user.is_authenticated:
        return redirect(url_for('home'))

    message = ""

    if request.method == "POST":

        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            save_user(username, email, password)
            return redirect(url_for('login'))

        except pymongo.errors.DuplicateKeyError:
            message = "User already exists"

    return render_template('signup.html', message=message)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/create-room/', methods=['GET', 'POST'])
@login_required
def create_room():

    message = ""

    if request.method == "POST":

        room_name = request.form.get('room_name')
        members = request.form.get('members')

        usernames = [
            username.strip()
            for username in members.split(',')
            if username.strip()
        ]

        if room_name:

            room_id = save_room(
                room_name,
                current_user.username
            )

            if current_user.username in usernames:
                usernames.remove(current_user.username)

            if usernames:
                add_room_members(
                    room_id,
                    room_name,
                    usernames,
                    current_user.username
                )

            return redirect(
                url_for(
                    'view_room',
                    room_id=room_id
                )
            )

        message = "Failed to create room"

    return render_template(
        'create_room.html',
        message=message
    )


@app.route('/rooms/<room_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_room(room_id):

    room = get_room(room_id)

    if not room:
        return "Room not found", 404

    if not is_room_admin(room_id, current_user.username):
        return "Access denied", 403

    existing_members = [
        member['_id']['username']
        for member in get_room_members(room_id)
    ]

    room_member_str = ",".join(existing_members)

    message = ""

    if request.method == 'POST':

        room_name = request.form.get('room_name')

        update_room(room_id, room_name)

        new_members = [
            username.strip()
            for username in request.form
            .get('members').split(',')
        ]

        members_to_add = list(
            set(new_members) - set(existing_members)
        )

        members_to_remove = list(
            set(existing_members) - set(new_members)
        )

        if members_to_add:
            add_room_members(
                room_id,
                room_name,
                members_to_add,
                current_user.username
            )

        if members_to_remove:
            remove_room_members(
                room_id,
                members_to_remove
            )

        room_member_str = ",".join(new_members)

        message = "Room updated successfully"

    return render_template(
        'edit_room.html',
        room=room,
        room_member_str=room_member_str,
        message=message
    )


@app.route('/rooms/<room_id>/messages')
@login_required
def get_older_messages(room_id):

    room = get_room(room_id)

    if room and is_room_member(
            room_id,
            current_user.username):

        page = int(request.args.get('page', 0))

        messages = get_messages(
            room_id,
            page
        )

        return dumps(messages)

    return "Room not found", 404



@app.route('/rooms/<path:room_id>/')
@login_required
def view_room(room_id):
    # Extract ObjectId if it's the full dict string
    match = re.search(r"ObjectId\('([a-f0-9]+)'\)", room_id)
    if match:
        room_id = match.group(1)
    
    print("ROOM_ID:", room_id)
    
    room = get_room(room_id)
    member_check = is_room_member(room_id, current_user.username)
    
    if room and member_check:
        room_members = get_room_members(room_id)
        messages = get_messages(room_id)
        return render_template(
            'view_room.html',
            username=current_user.username,
            room=room,
            room_members=room_members,
            messages=messages
        )

    return "Room not found", 404


@socketio.on('send_message')
def handle_send_message_event(data):

    data['created_at'] = datetime.now().strftime(
        "%d %b %H:%M"
    )

    save_message(
        data['room'],
        data['message'],
        data['username']
    )

    socketio.emit(
        'receive_message',
        data,
        room=data['room']
    )


@socketio.on('join_room')
def handle_join_room_event(data):

    join_room(data['room'])

    socketio.emit(
        'join_room_announcement',
        data,
        room=data['room']
    )


@socketio.on('leave_room')
def handle_leave_room_event(data):

    leave_room(data['room'])

    socketio.emit(
        'leave_room_announcement',
        data,
        room=data['room']
    )


if __name__ == "__main__":
    socketio.run(app,debug=True)