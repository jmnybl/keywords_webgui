from flask import Flask
import flask
import json
import requests
import subprocess
import os.path
import time
import hashlib
import psutil

DEBUGMODE=False
try:
    from config_local import * #use to override the constants above if you like
except ImportError:
    pass #no config_local

app = Flask("keywords_webgui")

TMPDIR="tmp_dir/"
RESDIR="static/results/"



def allow_rerun(hashed_json):
    """ First check web form rerun option, then json file whether job is still running. """
    if not flask.request.form.get('rerun'):
        print("Results exist.")
        return False
    with open(TMPDIR+hashed_json+".json","rt") as f:
        d=json.load(f)
    if psutil.pid_exists(d["pid"]) and psutil.Process(d["pid"]).status()!=psutil.STATUS_ZOMBIE: # ignore zombies
        print("Pid exist.",d["pid"])
        return False
    return True


def parse_form():
    """ Extract information from web form. !!! But do not use rerun option here, it's not supposed to be part of the json !!! """

    d=dict()

    errors, warnings=[],[]

    i=1
    keywords=[]
    uniq_words=set()
    while True:
        try:
            words=flask.request.form["keywords"+str(i)].strip().split()
            i+=1
            if len(words)>0:
                for w in set(words):
                    if w in uniq_words:
                        errors.append("Word <i>{word}</i> is in two different group, keyword lists must have unique words.".format(word=w))
                        return d,errors,warnings # return early
                uniq_words.update(set(words))
                keywords.append(sorted(set(words)))
        except:
            break

    
    d["keywords"]=keywords

    if len(d["keywords"])==0:
        errors.append("Error: No keywords defined.")
        return d,errors,warnings # return early

    d["random"]=False
    if len(d["keywords"])==1:
        if flask.request.form.get('random'): # use random sample only if user did not define two groups of keywords, otherwise add a warning
            d["random"]=True
        else:
            errors.append("Error: You must define either at least two groups of keywords, or click 'run against random text sample' option.")
            return d,errors,warnings # return early

    if len(d["keywords"])>1 and flask.request.form.get('random'):
        warnings.append("Warning: Random text sample -option ignored.")

    # lemma, case and adjective settings
    d["case_sensitive"]=False
    if flask.request.form.get('case'):
        d["case_sensitive"]=True

    d["lemma"]=False
    if flask.request.form.get('lemma'):
        d["lemma"]=True

    d["adjective"]=False
    if flask.request.form.get('adjective'):
        d["adjective"]=True


    return d,errors,warnings

@app.route("/")
def index():
    return flask.render_template("index_template.html")

@app.route('/query',methods=["POST"])
def query():

    d,errors,warnings=parse_form()

    if errors:
        errors.append("")
        errors.append("Job not submitted. Fix errors and try again.")
        ret=flask.render_template("err_tbl.html",messages=errors)
        return json.dumps({'ret':ret});
    
    
    print(json.dumps(d,sort_keys=True))
    
    

    # hash json
    hashed_json=hashlib.sha224(json.dumps(d,sort_keys=True).encode("utf-8")).hexdigest()

    # can we use ready results?
    if os.path.isfile(TMPDIR+hashed_json+".json"):
        # json file exists

        # if rerun==True and job is already finished --> rerun, otherwise just return the link to results and warning
        if allow_rerun(hashed_json)==False:
            with open(TMPDIR+hashed_json+".json","rt") as f:
                d=json.load(f)
            resurl=flask.url_for("static",filename="results/"+hashed_json+d["date"]+d["time"]+".html")
            warnings.append('Results for this experiment already exist <a href="{url}">here</a>. If you anyway want to run the experiment again, use rerun option.'.format(url=resurl))
            if flask.request.form.get('rerun'):
                warnings.append("Not possible to rerun while the same experiment is still running on the background.")
            warnings.append("")
            warnings.append("Job not submitted.")
            ret=flask.render_template("err_tbl.html",messages=warnings)
            return json.dumps({'ret':ret});



    # launch subprocess with this hash
    a=subprocess.Popen(["python3", "keywords.py", "--hash", hashed_json], shell=False) # TODO timeout

    # add time and pid to json (these are not part of the hashed version), store json
    d["date"]=time.strftime("%d-%m-%y")
    d["time"]=time.strftime("%H-%M-%S")
    d["pid"]=a.pid # process id to check whether it's still running

    with open("/".join((TMPDIR,hashed_json+".json")),"w") as f:
        json.dump(d, f, sort_keys=True)

    resurl=flask.url_for("static",filename="results/"+hashed_json+d["date"]+d["time"]+".html")


    # tell the user where results will then be
    if warnings:
        warnings.append("")
    warnings.append("Keywords: "+u" & ".join(",".join(klist) for klist in d["keywords"]))
    warnings.append("Random:"+str(d["random"])+" Case sensitive:"+str(d["case_sensitive"])+" Lemma:"+str(d["lemma"])+" Only adjectives:"+str(d["adjective"]))
    warnings.append("")
    warnings.append("Job launched {date} {time}.".format(date=d["date"],time=d["time"].replace("-",":")))
    warnings.append('Results will appear <a href="{url}">here</a>.'.format(url=resurl))

    print(resurl)

    ret=flask.render_template("err_tbl.html", messages=warnings)

    return json.dumps({'ret':ret});


if __name__ == '__main__':
    app.run(debug=DEBUGMODE)

