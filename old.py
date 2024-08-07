"""
import json
import subprocess
import time
import zipfile

import aiofiles
import boto3
from botocore.exceptions import NoCredentialsError
from pyunpack import Archive

from utils.email_notifier import send_mail
import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import tempfile
import rarfile
import shutil
import os
from redis import Redis
from rq import Queue
from starlette.responses import FileResponse, JSONResponse
from inference.infer_extraction import inference, inference_by_theme
from job import  process_music_from_docs, process_lyrics_from_theme,process_without_music_from_docs
from models.data_input import GenerateMusicRequest
from utils.extraction_ai import extraire_elements_key_from_context, format_to_human
from utils.googdrive.quickstart import upload_file_to_gdrive, upload_file_in_folder_to_gdrive

from utils.music_generator_ai import generate_music_lyrics, download_file_by_url
from utils.parsers_ai import MusicLyrics, Lyrics
from utils.sunowrapper.generate_song import fetch_feed, generate_music
from utils.tools import format_lyrics_single_refrain, format_lyrics_single_refrain
from rq.job import Job, Retry
from rq.registry import StartedJobRegistry, FinishedJobRegistry


load_dotenv()
app = FastAPI()
# Lire les variables d'environnement pour la configuration de Redis
redis_host = os.getenv("REDIS_HOST", "localhost")
redis_port = int(os.getenv("REDIS_PORT", 6379))

redis_conn = Redis(host=redis_host, port=redis_port)
task_queue=Queue("task_queue",connection=redis_conn,default_timeout=172800)

UPLOAD_DIR = "./uploads"
OUTPUT_DIR = "./output"
ZIP_OUTPUT_DIR = "zip_outputs/"
TEMP_DIR = "/media"

# Configure AWS S3
S3_BUCKET = "wimbucketstorage"
s3_client = boto3.client('s3', aws_access_key_id='AKIAZQ3DOIWH4GXKQBUP', aws_secret_access_key='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')

@app.post("/extract_elements_key_from_docs/",tags=['module'])
async def extract_elements_key_from_docs(
        file: UploadFile = File(..., description="Le document à traiter (Word, PDF, PowerPoint)"),
        orientation: str = Form(..., description="L'orientation du contexte à extraire du document"),
        min_char: int = Form(1000, description="Le nombre minimum de caractères pour le contexte extrait"),
        max_char: int = Form(1500, description="Le nombre maximum de caractères pour le contexte extrait"),
        niv_detail: int = Form(5, description="Le niveau de détail pour l'extraction (4 à 10)"),
        matiere:str= Form("",description="Nom de la matière concerné pour avoir une génération personnalisé"),
        niveau:str=Form("Terminale",description="Niveau de la classe"),
        langue:str=Form("Français",description="Langue de la génération")

):
    # Sauvegarder le fichier de manière permanente
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    print(f"File saved at: {file_path}")

    # Appeler la fonction d'inférence avec le chemin du fichier
    data = inference(
        file_path,
        orientation=orientation,
        min_nombre_caracteres=min_char,
        max_nombre_caracteres=max_char,
        matiere=matiere,
        niveau=niveau,
        langue=langue,
        k=niv_detail,

    )

    # Supprimer le fichier après traitement
    os.remove(file_path)
    print(f"File deleted: {file_path}")

    # Extraire les éléments de réponse
    elements = data['answer']

    return {"context": elements}


@app.post("/extract_elements_key_from_theme/",tags=['module'])
async def extract_elements_key_from_theme(
        theme: str = Form(..., description="Le thème pour générer les paroles"),
        orientation: str = Form("Comprendre l'intelligence artificielle et des exemples d'application",
                                description="L'orientation des paroles générées"),

        taille: int = Form(1300, description="La taille totale des paroles générées en nombre de caractères"),
    matiere: str = Form("", description="Nom de la matière concerné pour avoir une génération personnalisé"),
    niveau:str = Form("Terminale", description="Niveau de la classe"),
langue:str = Form("Français", description="Langue de la génération")
):
    # Appeler la fonction d'inférence avec le thème et l'orientation
    a = inference_by_theme(theme, orientation,niveau=niveau,langue=langue,matiere=matiere)
    tmp=extraire_elements_key_from_context(a, orientation, taille)

    return {"context": tmp.content}

@app.post("/generate_lyrics_from_elements_keys/",tags=['module'])
async def generate_lyrics_from_elements_key(
    elements: str = Form(..., description="Les éléments clés pour générer les paroles"),
    style: str = Form(..., description="Le style des paroles (par exemple, Rap, Pop, etc.)"),
    num_verses: int = Form(3, description="Le nombre de couplets à générer"),
    taille: int = Form(1300, description="La taille totale des paroles générées en nombre de caractères"),
    orientation: str = Form(..., description="L'orientation des paroles générées"),
        mode: str = Form("auto", description="Selectioon du choix du nombre couplets, auto / manuel"),

        langue: str = Form("Français", description="Langue de la génération")

):
    data = generate_music_lyrics(
        elements=elements,
        style=style,
        num_verses=num_verses,
        taille=taille,
        orientation=orientation,
        langue=langue,
        mode=mode
    )

    out = MusicLyrics.parse_obj(data).to_dict()
    tmp = format_to_human(out['lyrics'])
    print(tmp)

    out.update(Lyrics.parse_obj(tmp).to_dict())
    return out


@app.post("/generate_lyrics_docs/",tags=['text to lyrics'])
async def generate_lyrics_from_docs(
        file: UploadFile = File(..., description="Le document à traiter (Word, PDF, PowerPoint)"),
        orientation: str = Form(..., description="L'orientation du contexte à extraire du document"),
        min_char: int = Form(1000, description="Le nombre minimum de caractères pour le contexte extrait"),
        max_char: int = Form(1500, description="Le nombre maximum de caractères pour le contexte extrait"),
        niv_detail: int = Form(5, description="Le niveau de détail pour l'extraction (4 à 10)"),
    style: str = Form(..., description="Le style des paroles (par exemple, Rap, Pop, etc.)"),
    num_verses: int = Form(3, description="Le nombre de couplets à générer"),
    taille: int = Form(1500, description="La taille totale des paroles générées en nombre de caractères"),
        mode: str=Form("auto",description="Selectioon du choix du nombre couplets, auto / manuel"),
        matiere: str = Form("", description="Nom de la matière concerné pour avoir une génération personnalisé"),
        niveau: str = Form("Terminale", description="Niveau de la classe"),
        langue: str = Form("Français", description="Langue de la génération")

):
    # Sauvegarder le fichier de manière permanente
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    print(f"File saved at: {file_path}")

    # Appeler la fonction d'inférence avec le chemin du fichier
    data = inference(
        file_path,
        orientation=orientation,
        min_nombre_caracteres=min_char,
        max_nombre_caracteres=max_char,
        matiere=matiere,
        langue=langue,
        niveau=niveau,
        k=niv_detail,
    )

    # Supprimer le fichier après traitement
    os.remove(file_path)
    print(f"File deleted: {file_path}")

    # Extraire les éléments de réponse
    elements = data['answer']
    data = generate_music_lyrics(
        elements=elements,
        style=style,
        num_verses=num_verses,
        taille=taille,
        orientation=orientation,
        mode=mode,
        langue=langue

    )

    out = MusicLyrics.parse_obj(data).to_dict()
    tmp = format_to_human(out['lyrics'])
    print(tmp)

    out.update(Lyrics.parse_obj(tmp).to_dict())
    return out



@app.post("/generate_lyrics_theme/",tags=["text to lyrics"])
async def generate_lyrics_from_theme(
        theme: str = Form(..., description="Le thème pour générer les paroles"),
        orientation: str = Form("Comprendre l'intelligence artificielle et des exemples d'application",
                                description="L'orientation des paroles générées"),
        style: str = Form("Rap", description="Le style des paroles (par exemple, Rap, Pop, etc.)"),
        num_verses: int = Form(3, description="Le nombre de couplets à générer"),
        taille: int = Form(1400, description="La taille totale des paroles générées en nombre de caractères"),
        mode: str = Form("auto", description="Selectioon du choix du nombre couplets, auto / manuel"),
        matiere: str = Form("", description="Nom de la matière concerné pour avoir une génération personnalisé"),
        niveau: str = Form("Terminale", description="Niveau de la classe"),
        langue: str = Form("Français", description="Langue de la génération")

):
    # Appeler la fonction d'inférence avec le thème et l'orientation
    a = inference_by_theme(theme, orientation,matiere=matiere,langue=langue,niveau=niveau)
    tmp=extraire_elements_key_from_context(a, orientation, taille)


    # Générer les paroles de musique
    data = generate_music_lyrics(
        elements=tmp.content,
        style=style,
        num_verses=num_verses,
        taille=taille,
        orientation=orientation,
        mode=mode,
        langue=langue
    )


    return MusicLyrics.parse_obj(data)


@app.get("/get_music_ressource/{music_id}",tags=["ressource"])
def fetch_feed_endpoint(music_id: str):
    try:
        return fetch_feed(music_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate-music", response_model=list,tags=['module'])
def generate_music_endpoint(request: GenerateMusicRequest):

    try:
        return generate_music(request.lyrics, request.title, request.style)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate_music_from_multiple_docs/", tags=['old'])
async def generate_music_from_multi_docs(
        files: List[UploadFile] = File(..., description="Les documents à traiter (Word, PDF, PowerPoint)"),
        metadata_file: UploadFile = File(...,
                                         description="Fichier Excel ou CSV avec les paramètres d'orientation, taille, style, etc.")
):
    # Sauvegarder les fichiers de manière permanente
    file_paths = []
    for file in files:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        file_paths.append(file_path)

    metadata_path = os.path.join(UPLOAD_DIR, metadata_file.filename)
    with open(metadata_path, "wb") as f:
        shutil.copyfileobj(metadata_file.file, f)

    # Lire les métadonnées du fichier Excel ou CSV
    if metadata_path.endswith(".xlsx"):
        df = pd.read_excel(metadata_path)
    else:
        df = pd.read_csv(metadata_path)

    outputs = []

    for index, row in df.iterrows():
        doc_id = str(row['id'])
        orientation = row['orientation']

        niv_detail = row['niv_detail']
        style = row['style']
        langue=row['langue']
        niveau=row['niveau']
        matiere=row['matiere']


        print(row)
        # Trouver le fichier correspondant à l'id
        file_path = next((path for path in file_paths if os.path.basename(path).startswith(doc_id)), None)
        print(row['id'],file_path)
        if not file_path:
            continue

        # Appeler la fonction d'inférence avec le chemin du fichier
        data = inference(
            file_path,
            orientation=orientation,

            langue=langue,
            niveau=niveau,
            matiere=matiere,
            k=niv_detail,
        )

        # Supprimer le fichier après traitement
        os.remove(file_path)

        # Extraire les éléments de réponse
        elements = data['answer']
        data = generate_music_lyrics(
            elements=elements,
            style=style,

            orientation=orientation,
            langue=langue
        )

        out = MusicLyrics.parse_obj(data)
        tmp_dict = out.to_dict()
        tmp_dict['url'] = []
        tmp_dict["music"] = generate_music(format_lyrics_single_refrain(out.lyrics), out.title, out.style)
        time.sleep(500)
        print(tmp_dict)
        c = 1
        name = ""
        for id in tmp_dict["music"]:
            print(id)
            dat = fetch_feed(id)[0]
            print(dat)
            n = download_file_by_url(dat['audio_url'], )
            n2 = download_file_by_url(dat['image_large_url'], )
            name = dat["title"].replace(' ', '').lower()
            dat["url_drive"] = upload_file_in_folder_to_gdrive(n, f"{dat['title'].replace(' ', '').lower()}_v{c}.mp3",
                                                               '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s',
                                                               dat["title"].replace(' ', '').lower())
            dat["img_drive"] = upload_file_in_folder_to_gdrive(n2, f"{dat['title'].replace(' ', '').lower()}_v{c}.jpeg",
                                                               '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s',
                                                               dat["title"].replace(' ', '').lower())
            tmp_dict['url'].append(dat)
            c += 1

        # Sauvegarder le résultat sous forme de JSON avec encodage UTF-8
        output_path = os.path.join(OUTPUT_DIR, f"{file_path.split('.')[0].replace(' ', '')}_output.json")
        f = upload_file_in_folder_to_gdrive(output_path, f"data.json",
                                            '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s',
                                            name)
        with open(output_path, "w", encoding="utf-8") as json_file:
            json.dump(tmp_dict, json_file, ensure_ascii=False, indent=4)

        outputs.append(tmp_dict)
    # Créer un fichier ZIP contenant tous les fichiers JSON générés
    zip_path = os.path.join(ZIP_OUTPUT_DIR, "outputs.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, _, files in os.walk(OUTPUT_DIR):
            for file in files:
                zipf.write(os.path.join(root, file), arcname=file)
    # Supprimer tous les fichiers JSON dans OUTPUT_DIR
    for file in os.listdir(OUTPUT_DIR):
        file_path = os.path.join(OUTPUT_DIR, file)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")
    # Retourner l'URL pour télécharger le fichier ZIP
    zip_url = f"/download/{os.path.basename(zip_path)}"

    return {
        "download":zip_url,
        "data":outputs
    }

@app.post("/generate_lyrics_multiple_theme/", tags=["old"])
async def generate_lyrics_multi_from_theme(
        metadata_file: UploadFile = File(..., description="Fichier Excel avec les paramètres (thème, orientation, taille, etc.)")
):
    # Sauvegarder le fichier de métadonnées de manière permanente
    metadata_path = os.path.join(UPLOAD_DIR, metadata_file.filename)
    with open(metadata_path, "wb") as f:
        shutil.copyfileobj(metadata_file.file, f)

    # Lire les métadonnées du fichier Excel
    if metadata_path.endswith(".xlsx"):
        df = pd.read_excel(metadata_path)
    else:
        return JSONResponse(content={"message": "Le fichier doit être au format Excel (.xlsx)"}, status_code=400)

    outputs = []

    for index, row in df.iterrows():
        theme = row['theme']
        orientation = row['orientation']
        style = row['style']
        langue = row['langue']
        niveau = row['niveau']
        matiere = row['matiere']


        # Appeler la fonction d'inférence avec le thème et l'orientation
        a = inference_by_theme(theme, orientation,niveau=niveau,matiere=matiere,langue=langue)
        tmp = extraire_elements_key_from_context(a, orientation, )

        # Générer les paroles de musique
        data = generate_music_lyrics(
            elements=tmp.content,
            style=style,
            langue=langue,



            orientation=orientation,

        )

        out = MusicLyrics.parse_obj(data)
        tmp_dict = out.to_dict()
        tmp_dict['url']=[]
        tmp_dict["music"] = generate_music(format_lyrics_single_refrain(out.lyrics), out.title, out.style)
        time.sleep(500)
        print(tmp_dict)
        c=1
        name=""
        for id in tmp_dict["music"]:
            print(id)
            dat=fetch_feed(id)[0]
            print(dat)
            n=download_file_by_url(dat['audio_url'],)
            n2=download_file_by_url(dat['image_large_url'], )
            name=dat["title"].replace(' ', '').lower()
            dat["url_drive"]= upload_file_in_folder_to_gdrive(n, f"{dat['title'].replace(' ','').lower()}_v{c}.mp3", '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s', dat["title"].replace(' ','').lower())
            dat["img_drive"] = upload_file_in_folder_to_gdrive(n2, f"{dat['title'].replace(' ', '').lower()}_v{c}.jpeg",
                                                               '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s',
                                                               dat["title"].replace(' ', '').lower())
            tmp_dict['url'].append(dat)
            c+=1

        # Sauvegarder le résultat sous forme de JSON avec encodage UTF-8
        output_path = os.path.join(OUTPUT_DIR, f"{theme.replace(' ','')}_output.json")
        f=upload_file_in_folder_to_gdrive(output_path, f"data.json",
                                        '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s',
                                        name)
        with open(output_path, "w", encoding="utf-8") as json_file:
            json.dump(tmp_dict, json_file, ensure_ascii=False, indent=4)

        outputs.append(tmp_dict)


    # Créer un fichier ZIP contenant tous les fichiers JSON générés
    zip_path = os.path.join(ZIP_OUTPUT_DIR, "outputs.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, _, files in os.walk(OUTPUT_DIR):
            for file in files:
                zipf.write(os.path.join(root, file), arcname=file)

    # Supprimer tous les fichiers JSON dans OUTPUT_DIR
    for file in os.listdir(OUTPUT_DIR):
        file_path = os.path.join(OUTPUT_DIR, file)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")

    # Retourner l'URL pour télécharger le fichier ZIP
    zip_url = f"/download/{os.path.basename(zip_path)}"
    return {"zip_url": zip_url,
            "data":outputs}
"""