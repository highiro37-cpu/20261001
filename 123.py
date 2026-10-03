def push_state_to_cloud(val, sync_firebase=True, sync_blynk=True):
    val_int = 1 if int(val) == 1 else 0  # 確保強制轉換為整數 0 或 1
    
    if sync_firebase:
        try:
            res = urequests.put(f"{FIREBASE_URL}/door/status.json", json=val_int, timeout=1)
            res.close()
        except Exception:
            pass

    if sync_blynk:
        v10_val = 1 if val_int == 1 else 0
        v11_val = 255 if val_int == 1 else 0
        color = "%2300FF00" if val_int == 1 else "%23000000"

        path = f"/external/api/batch/update?token={BLYNK_TOKEN}&V10={v10_val}&V11={v11_val}&pin=V11&property=color&value={color}"
        fast_blynk_get(path)

    gc.collect()
