import bcrypt
from flask import Flask, make_response, request
import json
import mysql.connector

application = Flask(__name__)

db = None


def reconnectDB():
    global db
    # Should use an encrypted passowrd manager here such as Vault
    if db is None or not db.is_connected():
        db = mysql.connector.connect(
            host="ottawa-softball.cjohwnbqp2it.us-east-1.rds.amazonaws.com",
            user="admin",
            password="------",
            database="ottawasoftball"
        )


def getUserData(userID):
    reconnectDB()
    try:
        cursor = db.cursor(dictionary=True)
        sql = ('SELECT userID, firstName, teamID, role FROM User '
               'JOIN TeamMember AS tm ON User.ID = tm.userID '
               'WHERE User.ID = {userID};').format(userID=userID)
        cursor.execute(sql)
        results = cursor.fetchall()
        return {
            'userID': results[0]['userID'],
            'firstName': results[0]['firstName'],
            'teams': [{'teamID': result['teamID'], 'role': result['role']} for result in results],
        }
    except mysql.connector.Error as e:
        return 'Error getting user data'


@application.before_request
def connectToDb():
    reconnectDB()


@application.route('/')
def hello():
    return "Wow this is working"


@application.route('/user', methods=['POST'])
def addUser():
    data = json.loads(request.data.decode())
    try:
        cursor = db.cursor()
        sql = "INSERT INTO User (firstName, lastName, email, password) VALUES (%s, %s, %s, %s)"
        encryptedPassword = bcrypt.hashpw(data['password'].encode(), bcrypt.gensalt(13))
        val = (data['firstName'], data['lastName'], data['email'], encryptedPassword)
        cursor.execute(sql, val)
        db.commit()
        return make_response({'userID': cursor.lastrowid}, 200)
    except mysql.connector.Error as e:
        return make_response({'message': e.msg}, 400)


@application.route('/login', methods=['POST'])
def login():
    data = json.loads(request.data.decode())
    cursor = db.cursor(dictionary=True)
    sql = "SELECT * FROM User WHERE email=%s"
    cursor.execute(sql, (data['email'],))
    user = cursor.fetchone()
    if user is None:
        return make_response('Email not found', 404)
    if bcrypt.checkpw(data['password'].encode(), user['password'].encode()):
        teamsSql = 'select teamID, role from TeamMember where userID=%s; '
        cursor.execute(teamsSql, (user['ID'], ))
        teams = cursor.fetchall()
        return make_response({'message': 'Login successful', 'userID': user['ID'], 'teams': teams}, 200)
    else:
        return make_response('Incorrect password', 401)


@application.route('/games')
def getGames():
    cursor = db.cursor(dictionary=True)
    sql = ('SELECT Game.ID AS ID, home.name AS home, away.name AS away, field.name AS fieldName, field.address '
           'address, homeScore, awayScore, date FROM Game '
           'left JOIN Team AS home ON Game.homeID = home.ID '
           'left JOIN Team AS away ON Game.awayID = away.ID '
           'left JOIN Field field ON Game.fieldID = field.ID '
           'left JOIN TeamMember homeMember on home.ID = homeMember.teamID '
           'left JOIN TeamMember awayMember on away.ID = awayMember.teamID '
           'where homeMember.userID={userID} or awayMember.userID={userID} '
           'order by date asc;').format(userID=request.args['userID'])
    cursor.execute(sql)
    result = cursor.fetchall()
    if result is None:
        return make_response('No games found', 404)
    else:
        return make_response({'message': str(len(result)) + ' games found', 'games': result}, 200)


@application.route('/games', methods=['PUT'])
def updateScore():
    cursor = db.cursor(dictionary=True)
    try:
        data = json.loads(request.data.decode())
        sql = 'update Game set homeScore = %s, awayScore = %s where ID=%s;'
        cursor.execute(sql, (data['homeScore'], data['awayScore'], data['gameID']))
        db.commit()
        return make_response({'message': 'Successfully updated score'}, 200)
    except mysql.connector.Error as e:
        return make_response({'message': 'An error occurred while updating the database ' + e.msg}, 400)


@application.route('/teamMembers', methods=['GET', 'POST'])
def getTeamMembers():
    if request.method == 'GET':
        cursor = db.cursor(dictionary=True)
        sql = 'SELECT userID, role, firstName, lastName, email FROM TeamMember JOIN User ON userID=User.ID WHERE teamID=%s order by battingOrder asc'
        cursor.execute(sql, (request.args['teamID'],))
        result = cursor.fetchall()
        if result is None:
            return make_response({'message': 'No Team Members found'}, 404)
        else:
            return make_response({'teamMembers': result}, 200)
    elif request.method == 'POST':
        data = json.loads(request.data.decode())
        battingOrder = data['battingOrder']
        teamID = request.args['teamID']
        cursor = db.cursor()
        sql = 'UPDATE TeamMember SET battingOrder = %s WHERE teamID = ' + teamID + ' AND userID = %s'
        try:
            for index, val in enumerate(battingOrder):
                cursor.execute(sql, (index, val['userID']))
            db.commit()
            return make_response({'message': 'Successfully updated batting order'}, 200)
        except mysql.connector.Error as e:
            return make_response({'message': 'An error occurred while updating the database ' + e.msg}, 400)

    else:
        return "INVALID METHOD"


# Whenever you get innnings if none exist it will add one for each team
@application.route('/innings', methods=['GET', 'POST', 'PUT'])
def innings():
    if request.method == 'GET':
        gameID = request.args['gameID']
        gameInnings = getInnings(gameID)
        if len(gameInnings) == 0:
            addEmptyInning(gameID, 1)
        result = {'innings': getInnings(gameID)}
    elif request.method == 'POST':
        data = json.loads(request.data.decode())
        # addInning(data['gameID'], data['number'], data['teamID'], data['runs'])
        result = True
    if result is None:
        return make_response('An Error Occurred', 404)
    else:
        return make_response(result, 200)


def addEmptyInning(gameID, number):
    cursor = db.cursor(dictionary=True)
    sql = 'SELECT homeID, awayID FROM Game WHERE ID=%s'
    cursor.execute(sql, (gameID,))
    teams = cursor.fetchone()
    if teams is None:
        raise Exception('No Game found with that ID')
    cursor = db.cursor(dictionary=True)
    teamInningSql = 'INSERT INTO TeamInning (teamID, runs) VALUES (%s, %s)'
    cursor.execute(teamInningSql, (teams['homeID'], None))
    homeInningID = cursor.lastrowid
    cursor.execute(teamInningSql, (teams['awayID'], None))
    awayInningID = cursor.lastrowid
    sql = 'INSERT INTO Inning (homeInningID, awayInningID, number, gameID) VALUES (%s, %s, %s, %s)'
    cursor.execute(sql, (homeInningID, awayInningID, number, gameID))
    db.commit()


def getInnings(gameID):
    cursor = db.cursor(dictionary=True)
    sql = (
        'select homeInningID, awayInningID, number, gameID, home.runs as homeRuns, away.runs as awayRuns from Inning '
        'Join TeamInning home on homeInningID=home.ID '
        'Join TeamInning away on Inning.awayInningID=away.ID WHERE gameID=%s')
    cursor.execute(sql, (gameID,))
    result = cursor.fetchall()
    return result


if __name__ == '__main__':
    application.run()
