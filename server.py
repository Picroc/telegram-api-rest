from telethon import TelegramClient, utils, errors, crypto
from quart import session
import base64
import os

import hypercorn.asyncio
from quart_openapi import Pint, Resource
from quart_openapi.pint import jsonify, HTTPStatus
from quart_openapi.resource import request
from quart_openapi.cors import crossdomain
from quart_cors import route_cors, cors


def get_env(name, message):
    if name in os.environ:
        return os.environ[name]
    return input(message)


# Session name, API ID and hash to use; loaded from environmental variables
SESSION = 'server_test_toha'
API_ID = 1166576
API_HASH = '99db6db0082e27973ee4357e4637aadc'

session_clients = {}


async def create_session(session_key):
    if session_key in session_clients:
        return session_clients[session_key]['client']

    print('Creating new session client with key ', session_key)
    new_client = TelegramClient('api_test_' + session_key, API_ID, API_HASH)
    new_client.session.set_dc(2, '149.154.167.40', 443)
    session_clients[session_key] = {}
    session_clients[session_key]['client'] = new_client

    await new_client.connect()

    return new_client


# Quart app
app = Pint(__name__, title='apiMiddleware')
app.secret_key = 'Someday this war will end'
app = cors(app, allow_origin='http://localhost:8080', allow_credentials=True)

# VALIDATORS


# After we're done serving (near shutdown), clean up the client
@app.after_serving
async def cleanup():
    for client in session_clients.items():
        await client[1]['client'].disconnect()


@app.route('/')
class Root(Resource):
    async def get(self):
        '''Telegram API handler using Telethon

        Hello it is working'''
        return {"message": "hello"}


sendCodeValidate = app.create_validator('sendCode', {
    'type': 'object',
    'properties': {
            'phone_number': {
                'type': 'string',
                'description': 'Number to send code'
            }
    }
})


@app.route('/isAuthorized')
class isAuth(Resource):
    # @crossdomain('http://localhost:8080', credentials=True)
    # @route_cors(
    #     # allow_headers=["content-type"],
    #     # allow_methods=["POST"],
    #     allow_origin=["http://127.0.0.1:*"],
    #     allow_credentials=True
    # )
    async def get(self):
        await request.get_data()

        if(session.get('auth_session')):
            session_key = session.get('auth_session')

            client = await create_session(session_key)

            if await client.is_user_authorized():
                return jsonify({'status': 'AUTHORIZED'})
            else:
                return jsonify({'status': 'NOT_AUTHORIZED'})
        else:
            return jsonify({'status': 'NOT_AUTHORIZED'})


@app.route('/sendCode')
class SendCode(Resource):
    # @crossdomain(origin='http://localhost:8080', attach_to_all=True, headers=['content-type'], methods=['POST'], credentials=False)
    @app.expect(sendCodeValidate)
    async def post(self):
        await request.get_data()

        json = await request.get_json()
        phone = json['phone_number']

        print(json, phone)

        if session.get('auth_session'):
            session_key = session.get('auth_session')
        else:
            session_key = str(hash(phone))

        print(session_key)

        client = await create_session(session_key)

        # if await client.is_user_authorized():
        #     return {'status': 'ALREADY_AUTHORIZED'}

        try:
            sentData = await client.send_code_request(phone, force_sms=True)
        except errors.FloodWaitError as e:
            return {"status": "FLOOD_" + e.seconds}

        session_clients[session_key]['phone'] = phone
        session_clients[session_key]['phone_hash'] = sentData.phone_code_hash

        print('Setting key', session_key, 'for', phone)
        session['auth_session'] = session_key

        return {"status": "SENT"}


signInValidate = app.create_validator('sendCode', {
    'type': 'object',
    'properties': {
            'code': {
                'oneOf': [
                    {'type': 'string'},
                    {'type': 'integer'}
                ],
                'description': 'Number to send code'
            },
        'password': {
                'type': 'string',
                'description': 'Password for 2FA'
            }
    }
})


@app.route('/signIn')
class SignIn(Resource):
    # @crossdomain('http://localhost:8080', credentials=True)
    @app.expect(signInValidate)
    # @route_cors(
    #     # allow_headers=["content-type"],
    #     allow_origin=["http://127.0.0.1:63458"],
    #     allow_credentials=True
    # )
    async def post(self):
        await request.get_data()

        

        json = await request.get_json()
        code = json['code']
        password = json['password']

        session_key = session.get('auth_session')
        if not session_key or session_key not in session_clients:
            return {'status': 'NO_PENDING_AUTH'}

        client = await create_session(session_key)

        try:
            phone = session_clients[session_key]['phone']
        except KeyError:
            return jsonify({'status': 'NO_AUTH_PENDING'})
        phone_hash = session_clients[session_key]['phone_hash']

        print('Got number', phone)
        print('Got code', code)

        if await client.is_user_authorized():
            return {"status": "ALREADY_AUTHORIZED"}

        try:
            await client.sign_in(phone=str(phone), code=str(code), phone_code_hash=phone_hash, password=password)
        except errors.SessionPasswordNeededError:
            return {"status": "PASSWORD_NEEDED"}
        except errors.CodeInvalidError:
            return {"status": "CODE_INVALID"}
        except errors.PhoneNumberUnoccupiedError:
            session_clients[session_key]['code'] = code
            return {"status": "NOT_REGISTERED"}

        return {"status": "AUTHORIZED"}


@app.route('/signUp')
class SignUp(Resource):
    # @crossdomain('http://localhost:8080', credentials=True)
    @app.expect(signInValidate)
    # @route_cors(
    #     allow_headers=["content-type"],
    #     allow_methods=["POST, OPTIONS"],
    #     allow_origin=["http://127.0.0.1:63458"],
    #     allow_credentials=True
    # )
    async def post(self):
        await request.get_data()

        session_key = session.get('auth_session')
        if not session_key or session_key not in session_clients:
            return {'status': 'NO_PENDING_AUTH'}

        client = await create_session(session_key)

        json = await request.get_json()
        try:
            name = json['name']
            surname = json['surname']
        except KeyError:
            return {'status': 'WRONG_ARGUMENT'}

        phone = session_clients[session_key]['phone']
        phone_hash = session_clients[session_key]['phone_hash']
        code = session_clients[session_key]['code']

        try:
            await client.sign_up(first_name=name, last_name=surname, phone_code_hash=phone_hash, code=code, phone=phone)
        except errors.CodeInvalidError:
            return {'status': 'WRONG_CODE'}

        return {'status': 'USER_CREATED'}


@app.route('/getAllMessages')
class GetAllMessages(Resource):
    # @crossdomain('http://localhost:8080', credentials=True)
    async def get(self):
        return


@app.route('/uploadFile')
class UploadFile(Resource):
    async def post(self):
        await request.get_data()
        
        form = await request.form
        files = await request.files
        file = files.get('attach')
        
        session_key = session.get('auth_session')
        client = await create_session(session_key)
        file.save(file.filename)

        resp = await client.send_file('me', file.filename)

        print(resp)

        os.remove(file.filename)

        return 'Done'


# async def main():
#     await hypercorn.asyncio.serve(app, hypercorn.Config())


# By default, `Quart.run` uses `asyncio.run()`, which creates a new asyncio
# event loop. If we create the `TelegramClient` before, `telethon` will
# use `asyncio.get_event_loop()`, which is the implicit loop in the main
# thread. These two loops are different, and it won't work.
#
# So, we have to manually pass the same `loop` to both applications to
# make 100% sure it works and to avoid headaches.
#
# To run Quart inside `async def`, we must use `hypercorn.asyncio.serve()`
# directly.
#
# This example creates a global client outside of Quart handlers.
# If you create the client inside the handlers (common case), you
# won't have to worry about any of this, but it's still good to be
# explicit about the event loop.
if __name__ == '__main__':
    app.run('localhost', port=5000, debug=True)
