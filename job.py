import os
import shutil
import time
import zipfile
import pandas as pd
import json
from typing import List, Dict
from fastapi import UploadFile

from inference.infer_extraction import inference, inference_by_theme, inference_without_rag
from utils.extraction_ai import extraire_elements_key_from_context
from utils.googdrive.quickstart import upload_file_in_folder_to_gdrive

from utils.music_generator_ai import generate_music_lyrics, download_file_by_url
from utils.parsers_ai import MusicLyrics
from utils.sunowrapper.generate_song import generate_music, fetch_feed
from utils.tools import format_lyrics_single_refrain,format_lyrics

UPLOAD_DIR = "./uploads"
OUTPUT_DIR = "./output"
ZIP_OUTPUT_DIR = "zip_outputs/"


def process_music_from_docs(files: List[UploadFile], metadata_file: UploadFile) -> Dict:

    #model = load_whisper_model("small")
    file_paths = []
    for file in files:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        file_paths.append(file_path)

    metadata_path = os.path.join(UPLOAD_DIR, metadata_file.filename)
    with open(metadata_path, "wb") as f:
        shutil.copyfileobj(metadata_file.file, f)

    if metadata_path.endswith(".xlsx"):
        df = pd.read_excel(metadata_path)
    else:
        df = pd.read_csv(metadata_path)

    outputs = []

    for index, row in df.iterrows():
        doc_id = str(row['id'])
        orientation = row['orientation']
        niv_detail = 7
        style = row['style']
        langue = row['langue']
        niveau = row['niveau']
        matiere = row['matiere']

        file_path = next((path for path in file_paths if os.path.basename(path).startswith(doc_id)), None)
        if not file_path:
            continue

        data = inference(file_path, orientation=orientation, langue=langue, niveau=niveau, matiere=matiere,
                         k=niv_detail)
        os.remove(file_path)
        elements = data['answer']
        data = generate_music_lyrics(elements=elements, style=style, orientation=orientation, langue=langue)

        out = MusicLyrics.parse_obj(data)
        tmp_dict = out.to_dict()
        tmp_dict['url'] = []
        tmp_dict['langue'] = langue
        tmp_dict["music"] = generate_music(format_lyrics(out.lyrics), out.title, out.style)
        time.sleep(500)

        c = 1
        name = ""
        for id in tmp_dict["music"]:
            dat = fetch_feed(id)[0]

            n = download_file_by_url(dat['audio_url'])
            print(n)

            #dat['lrc_lyrics']=generate_audio_to_lrc(model, n)
            n2 = download_file_by_url(dat['image_large_url'])

            name = f"{doc_id}_folder"
            dat["url_drive"] = upload_file_in_folder_to_gdrive(n, f"{doc_id}_v{c}.mp3",
                                                               '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s',
                                                               name)
            dat["img_drive"] = upload_file_in_folder_to_gdrive(n2, f"{doc_id}_v{c}.jpeg",
                                                               '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s',
                                                              name)
            tmp_dict['url'].append(dat)
            c += 1

        output_path = os.path.join(OUTPUT_DIR, f"{doc_id}_output.json")

        with open(output_path, "w", encoding="utf-8") as json_file:
            json.dump(tmp_dict, json_file, ensure_ascii=False, indent=4)
        upload_file_in_folder_to_gdrive(output_path, f"data.json", '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s', name)
        outputs.append(tmp_dict)

    zip_path = os.path.join(ZIP_OUTPUT_DIR, "outputs.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, _, files in os.walk(OUTPUT_DIR):
            for file in files:
                zipf.write(os.path.join(root, file), arcname=file)

    for file in os.listdir(OUTPUT_DIR):
        file_path = os.path.join(OUTPUT_DIR, file)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")

    zip_url = f"/download/{os.path.basename(zip_path)}"
    return {"download": zip_url, "data": outputs}


def process_without_music_from_docs(files: List[UploadFile], metadata_file: UploadFile) -> Dict:
    #model = load_whisper_model("small")
    file_paths = []
    for file in files:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        file_paths.append(file_path)
    metadata_path = os.path.join(UPLOAD_DIR, metadata_file.filename)
    with open(metadata_path, "wb") as f:
        shutil.copyfileobj(metadata_file.file, f)

    if metadata_path.endswith(".xlsx"):
        df = pd.read_excel(metadata_path)
    else:
        df = pd.read_csv(metadata_path)

    outputs = []

    for index, row in df.iterrows():
        doc_id = str(row['id'])
        orientation = row['orientation']
        niv_detail = 7
        style = row['style']
        langue = row['langue']
        niveau = row['niveau']
        matiere = row['matiere']

        file_path = next((path for path in file_paths if os.path.basename(path).startswith(doc_id)), None)
        if not file_path:
            continue

        data = inference_without_rag(file_path, orientation=orientation, langue=langue, niveau=niveau, matiere=matiere,
                         k=niv_detail)
        os.remove(file_path)
        elements = data
        data = generate_music_lyrics(elements=elements, style=style, orientation=orientation, langue=langue)

        out = MusicLyrics.parse_obj(data)
        tmp_dict = out.to_dict()
        tmp_dict['url'] = []
        tmp_dict['langue'] = langue
        tmp_dict["music"] = generate_music(format_lyrics(out.lyrics), out.title, out.style)
        time.sleep(500)

        c = 1
        name = ""
        for id in tmp_dict["music"]:
            dat = fetch_feed(id)[0]

            n = download_file_by_url(dat['audio_url'])
            print(n)

            #dat['lrc_lyrics']=generate_audio_to_lrc(model, n)
            n2 = download_file_by_url(dat['image_large_url'])

            name = f"{doc_id}_folder"
            dat["url_drive"] = upload_file_in_folder_to_gdrive(n, f"{doc_id}_v{c}.mp3",
                                                               '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s',
                                                               name)
            dat["img_drive"] = upload_file_in_folder_to_gdrive(n2, f"{doc_id}_v{c}.jpeg",
                                                               '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s',
                                                              name)
            tmp_dict['url'].append(dat)
            c += 1

        output_path = os.path.join(OUTPUT_DIR, f"{doc_id}_output.json")

        with open(output_path, "w", encoding="utf-8") as json_file:
            json.dump(tmp_dict, json_file, ensure_ascii=False, indent=4)
        upload_file_in_folder_to_gdrive(output_path, f"data.json", '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s', name)
        outputs.append(tmp_dict)

    zip_path = os.path.join(ZIP_OUTPUT_DIR, "outputs.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, _, files in os.walk(OUTPUT_DIR):
            for file in files:
                zipf.write(os.path.join(root, file), arcname=file)

    for file in os.listdir(OUTPUT_DIR):
        file_path = os.path.join(OUTPUT_DIR, file)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")

    zip_url = f"/download/{os.path.basename(zip_path)}"
    return {"download": zip_url, "data": outputs}


def process_lyrics_from_theme(metadata_file: UploadFile) -> Dict:
    #model = load_whisper_model("small")
    metadata_path = os.path.join(UPLOAD_DIR, metadata_file.filename)
    with open(metadata_path, "wb") as f:
        shutil.copyfileobj(metadata_file.file, f)

    if metadata_path.endswith(".xlsx"):
        df = pd.read_excel(metadata_path)
    else:
        raise ValueError("Le fichier doit être au format Excel (.xlsx)")

    outputs = []

    for index, row in df.iterrows():
        theme = row['theme']
        orientation = row['orientation']
        style = row['style']
        langue = row['langue']
        niveau = row['niveau']
        matiere = row['matiere']

        a = inference_by_theme(theme, orientation, niveau=niveau, matiere=matiere, langue=langue)
        tmp = extraire_elements_key_from_context(a, orientation)

        data = generate_music_lyrics(elements=tmp.content, style=style, langue=langue, orientation=orientation)
        out = MusicLyrics.parse_obj(data)
        tmp_dict = out.to_dict()
        tmp_dict['url'] = []
        tmp_dict['langue']=langue
        tmp_dict["music"] = generate_music(format_lyrics(out.lyrics), out.title, out.style)
        time.sleep(500)

        c = 1
        name = ""
        for id in tmp_dict["music"]:
            dat = fetch_feed(id)[0]
            n = download_file_by_url(dat['audio_url'])
            #dat['lrc_lyrics'] = generate_audio_to_lrc(model, n)
            n2 = download_file_by_url(dat['image_large_url'])
            name = dat["title"].replace(' ', '').lower()
            dat["url_drive"] = upload_file_in_folder_to_gdrive(n, f"{dat['title'].replace(' ', '').lower()}_v{c}.mp3",
                                                               '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s',
                                                               dat["title"].replace(' ', '').lower())
            dat["img_drive"] = upload_file_in_folder_to_gdrive(n2, f"{dat['title'].replace(' ', '').lower()}_v{c}.jpeg",
                                                               '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s',
                                                               dat["title"].replace(' ', '').lower())
            tmp_dict['url'].append(dat)
            c += 1

        output_path = os.path.join(OUTPUT_DIR, f"{theme.replace(' ', '')}_output.json")

        with open(output_path, "w", encoding="utf-8") as json_file:
            json.dump(tmp_dict, json_file, ensure_ascii=False, indent=4)
        upload_file_in_folder_to_gdrive(output_path, f"data.json", '1GKdhuP-dnsHQgmhgKoYAVDlscWbLZ-2s', name)
        outputs.append(tmp_dict)

    zip_path = os.path.join(ZIP_OUTPUT_DIR, "outputs.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, _, files in os.walk(OUTPUT_DIR):
            for file in files:
                zipf.write(os.path.join(root, file), arcname=file)

    for file in os.listdir(OUTPUT_DIR):
        file_path = os.path.join(OUTPUT_DIR, file)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")

    zip_url = f"/download/{os.path.basename(zip_path)}"
    return {"zip_url": zip_url, "data": outputs}
