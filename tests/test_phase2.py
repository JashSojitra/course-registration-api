from fastapi import FastAPI
from fastapi.testclient import TestClient
from student_api import router,students
from concurrent.futures import ThreadPoolExecutor
app=FastAPI();app.include_router(router);client=TestClient(app)

def html(rows):
    head='<tr><th>Status</th><th>Course</th><th>Title</th><th>Grade</th><th>Term</th><th>Credits</th></tr>'
    return '<table>'+head+''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</table>'

def test_import_dedup():
    students.clear()
    content=html([('Completed','ABC-100','Intro','P','24F','3'),('Completed','ABC-100','Intro','84','24F','2'),('Completed','ABC-100','Intro','84','24F','3'),('Attempted','LAB-001','Lab','F','25W',''),('Planned','NON-1','','','26F','3'),('Completed','NON-2','','88','','3')])
    r=client.post('/api/v1/students/a/history/import',files={'file':('t.html',content)})
    assert r.status_code==201,r.text
    assert r.json()['past_courses_imported']==2
    courses=client.get('/api/v1/students/a/profile').json()['history']
    assert courses==[{'course_code':'ABC-100','term':'24F','credits_earned':3,'status':'Completed'},{'course_code':'LAB-001','term':'25W','credits_earned':0,'status':'Attempted'}]

def test_lifecycle_isolation():
    students.clear()
    def imp(s,c):return client.post(f'/api/v1/students/{s}/history/import',files={'file':('x.html',html([('Completed',c,'X','A','25F','3')]))})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda args:imp(*args), [('one','A-1'),('two','B-1')]))
    assert all(r.status_code==201 for r in results)
    assert client.get('/api/v1/students/one/profile').json()['history'][0]['course_code']=='A-1'
    assert client.get('/api/v1/students/two/profile').json()['history'][0]['course_code']=='B-1'
    assert client.post('/api/v1/students/unknown/plan',json={'planned_courses':[]}).status_code==404
    assert client.get('/api/v1/students/unknown/profile').status_code==404
    assert client.post('/api/v1/students/one/plan',json={'planned_courses':[{'course_code':'X-2','term':'26F'}]}).status_code==200
    assert client.put('/api/v1/students/one/history',json={'history':[]}).status_code==200
    assert client.get('/api/v1/students/one/profile').json()['plan'][0]['course_code']=='X-2'
    assert client.put('/api/v1/students/one/plan',json={'planned_courses':[]}).status_code==200
    assert client.delete('/api/v1/students/one/plan').status_code==200
    assert client.delete('/api/v1/students/one/history').status_code==200
    assert client.patch('/api/v1/students/one/plan').status_code==405
