import sys
import json
import conllutil3 as cu
import sklearn.feature_extraction
from sklearn.svm import LinearSVC
import argparse
import requests
from collections import defaultdict
import jinja2
from random import shuffle
import traceback

TMPDIR="tmp_dir/"
RESDIR="static/results/"


#def formulate_query(words,random,lemma):
##    words=['"'+w+'"' for w in words] # escape special characters, not able use this if this will be dep_search queries TODO: fix dep_search lemma
#    if lemma:
#        q="|".join("L="+w for w in words)
#    else:
#        q="|".join(words)
#    if random: # negate the query
#        #q="!(_ + "+q.replace("|","&")+")"
#        q="_ -> !("+q.replace("|","&")+")"
#    print(q)
#    return q


def collect_data(query,stopwords=set(),case_sensitive=False,lemma=False,adjective=False,max_sent=10000):
    """ If random=True, use random sentences not containing the given words
        stopwords is a set of words which should be masked (removed)    
    """
    results=[]
    sent=[]
    r=requests.get("http://epsilon-it.utu.fi/dep_search_webapi",params={"db":"PBV4", "search":query, "case":case_sensitive, "retmax":max_sent, "shuffle":True},stream=True)
    #print("Getting",r.url,file=sys.stderr)
    for hit in r.iter_lines():
        # hit is a line
        hit=hit.decode("utf-8").strip()
        #print("HIT:::",hit,file=sys.stderr)
        if not hit: # sentence break
            if sent:
                results.append(" ".join(sent))
                sent=[]
            continue
        if hit.startswith("#"):
            continue
        else:
            hit=hit.split("\t")
            if adjective==True and hit[cu.CPOS]!="ADJ":
                continue
            if lemma:
                if hit[cu.LEMMA].lower().replace("-","").replace("#","") not in stopwords: # case insensitive lemmas
                    sent.append(hit[cu.LEMMA].lower())

            else:
                if hit[cu.FORM].lower() not in stopwords:
                    sent.append(hit[cu.FORM].lower())
    else:
        if sent:
            results.append(" ".join(sent))

    return results

def collect_data_korp(words=[],stopwords=set(),corpus="s24_001,s24_002,s24_003,s24_004,s24_005,s24_006,s24_007,s24_008,s24_009,s24_010",random=False,case_sensitive=False,lemma=False,adjective=False,max_sent=10000):
    """ If random=True, use random sentences not containing the given words
        stopwords is a set of words which should be masked (removed)    
    """


    if lemma:
        form="lemma"
    else:
        form="word"
    if case_sensitive:
        case=""
    else:
        case="(?i)"
    if random:
        neg="!"
    else:
        neg=""
    expressions=[]
    for word in words:
        word=word.replace(":","\:").replace(")","\)").replace("(","\(").replace("|","\|")
        expressions.append('[{N}({F} = "{C}{W}")]'.format(N=neg,F=form,C=case,W=word)) # '([word = "(?i)kreikka"]|[word = "(?i)kreikkalainen"])'

    cqp_query="|".join(e for e in expressions) 

    extra='&defaultcontext=1+sentence&defaultwithin=sentence&show=sentence,paragraph,lemma,pos&show_struct=sentence_id&start=0&end={M}'.format(M=max_sent)

    url="https://korp.csc.fi/cgi-bin/korp.cgi?command={command}{extra_param}&corpus={C}&cqp={cqp}".format(command="query",extra_param=extra,C=corpus,cqp=cqp_query)

    #print("Getting url:",url,file=sys.stderr)
    
    hits=requests.get(url)

    data=hits.json()
   # print(data["kwic"][0]['tokens'])
    sent_ids=set()

    if "kwic" not in data:
        #print("No results...")
        return []
    results=[]
    for sent in data["kwic"]:
        idx=sent["structs"]["sentence_id"]
        if idx in sent_ids:
            continue
        sent_ids.add(idx)
    #    print(sent)
        sentence=[]
        for token in sent['tokens']:
            if (token["word"] is not None) and (form in token) and (token[form].lower() not in stopwords):
                if adjective and (("pos" not in token) or (token["pos"]!="A")):
                    continue
                sentence.append(token[form].lower())
        if sentence:
            results.append(" ".join(sentence))
    return results


def simple_tokenizer(txt):
    """ Simple tokenizer, default one splits hyphens and other weirdish stuff. """
    return txt.split(" ")

def train_svm(data,labels):

    vectorizer=sklearn.feature_extraction.text.TfidfVectorizer(tokenizer=simple_tokenizer,max_df=0.3,sublinear_tf=True,use_idf=False)

    d=vectorizer.fit_transform(data)

    classifier = LinearSVC(C=0.1)
    classifier.fit(d,labels)

    features=[]
    f_names=vectorizer.get_feature_names()
    for i,class_vector in enumerate(classifier.coef_):
        sorted_by_weight=sorted(zip(class_vector,f_names), reverse=True)
        features.append([])
        for f_weight,f_name in sorted_by_weight[:50]:
            features[-1].append((f_name,"{:.3}".format(f_weight)))
    if len(classifier.coef_)==1: # use negative features
        sorted_by_weight=sorted(zip(classifier.coef_[0],f_names))
        features.insert(0,[]) # these are features for first class
        for f_weight,f_name in sorted_by_weight[:50]:
            features[0].append((f_name,"{:.3}".format(f_weight*-1)))

    return features



def generate_html(fname,path,messages=[],features=[],ready=False):
    if len(features)<=6:
        fcol=2
        emptydiv=12-len(features)*fcol
    elif len(features)<=12:
        fcol=1
        emptydiv=12-len(features)*fcol
    else:
        fcol=1
        emptydiv=0
    with open(fname,"wt") as f:
        template=jinja2.Environment(loader=jinja2.FileSystemLoader("./templates/")).get_template("result_tbl.html")
        print(template.render({"path":path,"messages":messages,"features":features,"ready":ready,"fcol":fcol,"emptydiv":emptydiv}),file=f)



korpdef={"PB":"PB","S24":"s24_001,s24_002,s24_003,s24_004,s24_005,s24_006,s24_007,s24_008,s24_009,s24_010"}
def main(hashed_json,path):
    # read json to get correct settings
    with open(TMPDIR+hashed_json+".json","rt") as f:
        d=json.load(f)

    fname=u"".join((RESDIR,hashed_json,d["date"],d["time"],".html"))
    info=[]
    info.append(d["date"]+" "+d["time"].replace("-",":"))
    if d["corpus"]=="PB":
        info.append("Keywords: "+str(d["keywords"]))
        print(d["keywords"])
    else:
        info.append("Keywords: "+u"   &   ".join(",".join(klist) for klist in d["keywords"]))
    info.append("Random:"+str(d["random"])+"   Case sensitive:"+str(d["case_sensitive"])+"   Lemma:"+str(d["lemma"])+"   Only adjectives:"+str(d["adjective"]))
    generate_html(fname,path,messages=info)

    class_names=[]
    labels=[]
    dataset=[]

    if d["corpus"]!="PB":
        uniq_words=set([w.lower() for sublist in d["keywords"] for w in sublist]) # set of unique words to use in masking
    else:
        uniq_words=set()
    
    try:
        # collect data
        for wordlist in d["keywords"]:
            if d["corpus"]=="PB":        
                data=collect_data(wordlist,stopwords=uniq_words,case_sensitive=d["case_sensitive"],lemma=d["lemma"],adjective=d["adjective"])
            else:
                data=collect_data_korp(words=wordlist,stopwords=uniq_words,corpus=korpdef[d["corpus"]],random=False,case_sensitive=d["case_sensitive"],lemma=d["lemma"],adjective=d["adjective"])
            shuffle(data)
            random=data[:5000]
            if d["corpus"]=="PB":
                info.append(wordlist+" dataset size: {r}/{a}".format(r=str(len(random)),a=str(len(data))))   
            else: 
                info.append(u",".join(wordlist)+" dataset size: {r}/{a}".format(r=str(len(random)),a=str(len(data))))
            generate_html(fname,path,messages=info)
            if data:
                if isinstance(wordlist,list):
                    class_names.append(u",".join(wordlist))
                else:
                    class_names.append(wordlist)
                dataset+=random
                labels+=[len(class_names)-1]*len(random)
        if len(class_names)==1 and d["random"]==True:
            data=collect_data_korp(words=d["keywords"][0],stopwords=uniq_words,corpus=korpdef[d["corpus"]],random=True,case_sensitive=d["case_sensitive"],lemma=d["lemma"],adjective=d["adjective"])
            shuffle(data)
            random=data[:5000]
            info.append(u"Contrastive dataset size: {r}/{a}".format(r=str(len(random)),a=str(len(data))))
            generate_html(fname,path,messages=info)
            if data:
                class_names.append("Contrastive")
                dataset+=random
                labels+=[len(class_names)-1]*len(random)

        # train svm
        features=train_svm(dataset,labels)
        flists=[]
        for i,feats in enumerate(features):
#            if class_names[i]=="Contrastive":
#                query=formulate_query(class_names[0].split(","),True,d["lemma"])
#            else:
#                query=formulate_query(class_names[i].split(","),False,d["lemma"])
#            link2query="<a href='http://epsilon-it.utu.fi/dep_search_webgui/query?db=S24&search={q}'>{text}</a>".format(q=query,text=class_names[i])
            link2query=class_names[i]
            print(link2query)
            flists.append((link2query,feats))

    except Exception as e:

        print(e)
        traceback.print_exc()
        info.append("Error: "+str(e))
        flists=[]

    info.append("Done. This page will stay static, you can save the link to access the results also later.")
    generate_html(fname,path,messages=info,features=flists,ready=True)



if __name__=="__main__":
    parser = argparse.ArgumentParser(description='')
    parser.add_argument('--hash', type=str, help='Hash of the jsoned settings')
    parser.add_argument('--path', type=str, help='Path for style files')
    args = parser.parse_args()

    main(args.hash,args.path)


