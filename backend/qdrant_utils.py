import uuid
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from qdrant_client.http.models import VectorParams as HttpVectorParams
from qdrant_client.http.models import Filter, FieldCondition, MatchValue, PayloadSchemaType, FilterSelector

COLLECTION = "chat_chunks"
def delete_session(client, session_id: str):
    f = Filter(must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))])
    client.delete(
        collection_name=COLLECTION,
        points_selector=FilterSelector(filter=f),
        wait=True
    )
def connect(url: str, api_key: str | None = None):
    return QdrantClient(url=url, api_key=api_key)
def ensure_payload_indexes(client):
    for field in ("session_id", "source", "file_type"):
        try:
            client.create_payload_index(
                collection_name=COLLECTION,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD
            )
        except Exception:
            pass

def ensure_collection(client, dim: int):
    cols = client.get_collections().collections
    if not any(c.name == COLLECTION for c in cols):
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        return

    info = client.get_collection(COLLECTION)
    cfg = info.config.params.vectors
    if isinstance(cfg, HttpVectorParams):
        if cfg.size != dim or cfg.distance != Distance.COSINE:
            raise RuntimeError(
                f"Kolekcja '{COLLECTION}' ma {cfg.size}/{cfg.distance}, "
                f"oczekiwano {dim}/{Distance.COSINE}"
            )
def upsert_chunks(client: QdrantClient, vectors, payloads):
    points = [PointStruct(id=str(uuid.uuid4()), vector=v, payload=p) for v, p in zip(vectors, payloads)]
    client.upsert(collection_name=COLLECTION, points=points,  wait=True)

def search(client, vector, k: int = 8, session_id: str | None = None):
    qfilter = None
    if session_id:
        qfilter = Filter(must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))])

    return client.search(
        collection_name=COLLECTION,
        query_vector=vector,
        limit=k,
        with_payload=True,
        query_filter=qfilter
    )
