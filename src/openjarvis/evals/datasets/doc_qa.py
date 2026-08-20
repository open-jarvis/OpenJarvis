"""doc_qa dataset — 30 document-grounded QA tasks.

Each task provides 3-6 real-world documentation excerpts and a question.
The agent must answer using only the provided documents and cite sources.

Difficulty tiers:
- easy (10): answer in a single document, straightforward extraction
- medium (10): answer requires synthesizing 2-3 documents
- hard (10): answer requires reasoning across documents with distractors
"""

from __future__ import annotations

import random
from typing import Any, Dict, Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord

_PROMPT_TEMPLATE = """Answer the following question using ONLY the provided documents. Cite which document(s) support each claim (e.g., [Doc 1], [Doc 3]).

## Question
{question}

## Documents

{documents}

Provide a clear, well-structured answer with citations."""

# ---------------------------------------------------------------------------
# EASY tasks (10): single-doc extraction
# ---------------------------------------------------------------------------

_EASY_TASKS: List[Dict[str, Any]] = [
    {
        "question": "What is the purpose of PostgreSQL's VACUUM command?",
        "documents": [
            {
                "title": "PostgreSQL: VACUUM",
                "content": "VACUUM reclaims storage occupied by dead tuples. In normal PostgreSQL operation, tuples that are deleted or obsoleted by an update are not physically removed from their table; they remain present until a VACUUM is done. Therefore it's necessary to do VACUUM periodically, especially on frequently-updated tables.",
            },
            {
                "title": "PostgreSQL: CREATE INDEX",
                "content": "CREATE INDEX constructs an index on the specified column(s) of the specified relation. Indexes are primarily used to enhance database performance. An index defined on a table column that is part of a join condition can also significantly speed up queries with joins.",
            },
            {
                "title": "PostgreSQL: EXPLAIN",
                "content": "EXPLAIN displays the execution plan that the PostgreSQL planner generates for the supplied statement. The execution plan shows how the table(s) referenced by the statement will be scanned.",
            },
        ],
        "required_facts": [
            {"fact": "reclaims storage from dead tuples", "source_doc_index": 0},
            {
                "fact": "deleted or updated tuples remain until VACUUM",
                "source_doc_index": 0,
            },
        ],
    },
    {
        "question": "How does Redis persistence work with RDB snapshots?",
        "documents": [
            {
                "title": "Redis: RDB Persistence",
                "content": "RDB persistence performs point-in-time snapshots of your dataset at specified intervals. Redis forks a child process to write the dataset to a temporary file on disk, then atomically replaces the old file. This allows Redis to benefit from copy-on-write semantics. RDB files are compact and perfect for backups.",
            },
            {
                "title": "Redis: AOF Persistence",
                "content": "AOF persistence logs every write operation received by the server. These operations can then be replayed again at server startup, reconstructing the original dataset. Commands are logged using the same format as the Redis protocol itself.",
            },
            {
                "title": "Redis: Memory Management",
                "content": "Redis manages memory using a configurable maxmemory directive. When the limit is reached, Redis applies an eviction policy to remove keys. Available policies include volatile-lru, allkeys-lru, volatile-random, allkeys-random, and noeviction.",
            },
        ],
        "required_facts": [
            {"fact": "point-in-time snapshots at intervals", "source_doc_index": 0},
            {"fact": "forks child process", "source_doc_index": 0},
            {"fact": "compact files good for backups", "source_doc_index": 0},
        ],
    },
    {
        "question": "What are Kubernetes network policies used for?",
        "documents": [
            {
                "title": "K8s: Network Policies",
                "content": "NetworkPolicies are an application-centric construct which allow you to specify how a pod is allowed to communicate with various network entities. The entities that a Pod can communicate with are identified through a combination of namespaceSelector, podSelector, and ipBlock. By default, pods are non-isolated and accept traffic from any source.",
            },
            {
                "title": "K8s: Services",
                "content": "A Service is an abstract way to expose an application running on a set of Pods as a network service. Kubernetes gives Pods their own IP addresses and a single DNS name for a set of Pods, and can load-balance across them.",
            },
            {
                "title": "K8s: Ingress",
                "content": "Ingress exposes HTTP and HTTPS routes from outside the cluster to services within the cluster. Traffic routing is controlled by rules defined on the Ingress resource.",
            },
        ],
        "required_facts": [
            {"fact": "specify how pods communicate", "source_doc_index": 0},
            {"fact": "namespaceSelector podSelector ipBlock", "source_doc_index": 0},
            {"fact": "pods are non-isolated by default", "source_doc_index": 0},
        ],
    },
    {
        "question": "How do FastAPI dependencies work?",
        "documents": [
            {
                "title": "FastAPI: Dependencies",
                "content": "FastAPI has a very powerful but intuitive Dependency Injection system. It is designed to be very simple to use, and to make it very easy for any developer to integrate other components with FastAPI. Dependencies can be declared as function parameters using Depends(). FastAPI will call the dependency function, get the result, and pass it to your function.",
            },
            {
                "title": "FastAPI: Path Operations",
                "content": "You can declare path operation functions with Python type hints. FastAPI uses these type hints to validate data, serialize output, and generate documentation automatically.",
            },
            {
                "title": "FastAPI: Middleware",
                "content": "Middleware is a function that works with every request before it is processed by any specific path operation. It also handles every response before returning it. You add middleware using app.add_middleware().",
            },
        ],
        "required_facts": [
            {"fact": "dependency injection system", "source_doc_index": 0},
            {"fact": "Depends() function parameter", "source_doc_index": 0},
        ],
    },
    {
        "question": "What is Python's pathlib module used for?",
        "documents": [
            {
                "title": "Python: pathlib",
                "content": "The pathlib module offers classes representing filesystem paths with semantics appropriate for different operating systems. Path classes are divided between pure paths, which provide purely computational operations without I/O, and concrete paths, which inherit from pure paths but also provide I/O operations. Path objects can be used with os.scandir() and other functions expecting string paths.",
            },
            {
                "title": "Python: os.path",
                "content": "The os.path module implements some useful functions on pathnames. This module is always available. Unlike pathlib, os.path operates on strings rather than path objects.",
            },
            {
                "title": "Python: shutil",
                "content": "The shutil module offers a number of high-level operations on files and collections of files. In particular, functions are provided which support file copying and removal.",
            },
        ],
        "required_facts": [
            {"fact": "classes representing filesystem paths", "source_doc_index": 0},
            {"fact": "pure paths and concrete paths", "source_doc_index": 0},
        ],
    },
    {
        "question": "How does nginx reverse proxy configuration work?",
        "documents": [
            {
                "title": "nginx: Reverse Proxy",
                "content": "To configure a basic reverse proxy, use the proxy_pass directive inside a location block. For example, proxy_pass http://backend; forwards all requests to the backend server group. nginx can also modify request headers using proxy_set_header, and buffer responses using proxy_buffering.",
            },
            {
                "title": "nginx: Load Balancing",
                "content": "nginx can distribute traffic across multiple servers using upstream blocks. Methods include round-robin (default), least_conn (fewest active connections), and ip_hash (session persistence based on client IP).",
            },
            {
                "title": "nginx: SSL/TLS",
                "content": "To enable HTTPS, configure ssl_certificate and ssl_certificate_key directives in the server block. nginx supports TLS 1.2 and 1.3 by default.",
            },
        ],
        "required_facts": [
            {"fact": "proxy_pass directive in location block", "source_doc_index": 0},
            {"fact": "proxy_set_header modifies headers", "source_doc_index": 0},
        ],
    },
    {
        "question": "What are Python asyncio tasks?",
        "documents": [
            {
                "title": "Python: asyncio Tasks",
                "content": "Tasks are used to schedule coroutines concurrently. When a coroutine is wrapped into a Task with functions like asyncio.create_task(), the coroutine is automatically scheduled to run soon. Tasks are used to run coroutines in event loops. If a coroutine awaits a Future, the Task suspends the execution of the coroutine and waits for the completion of the Future.",
            },
            {
                "title": "Python: asyncio Event Loop",
                "content": "The event loop is the core of every asyncio application. Event loops run asynchronous tasks and callbacks, perform network IO operations, and run subprocesses. Application developers should typically use the high-level asyncio functions, such as asyncio.run().",
            },
            {
                "title": "Python: threading",
                "content": "The threading module constructs higher-level threading interfaces on top of the lower level _thread module. The Thread class represents an activity that is run in a separate thread of control.",
            },
        ],
        "required_facts": [
            {"fact": "schedule coroutines concurrently", "source_doc_index": 0},
            {"fact": "asyncio.create_task()", "source_doc_index": 0},
        ],
    },
    {
        "question": "What is Kubernetes RBAC?",
        "documents": [
            {
                "title": "K8s: RBAC",
                "content": "Role-based access control (RBAC) is a method of regulating access to computer or network resources based on the roles of individual users. RBAC uses rbac.authorization.k8s.io API group to drive authorization decisions. A Role sets permissions within a namespace, while a ClusterRole is non-namespaced. RoleBinding binds a Role to subjects (users, groups, or service accounts).",
            },
            {
                "title": "K8s: Service Accounts",
                "content": "A ServiceAccount provides an identity for processes that run in a Pod. When you create a pod, if you do not specify a service account, it is automatically assigned the default service account in the same namespace.",
            },
            {
                "title": "K8s: Pod Security",
                "content": "Pod Security Standards define three different policies to broadly cover the security spectrum. These policies are cumulative and range from highly-permissive to highly-restrictive.",
            },
        ],
        "required_facts": [
            {"fact": "role-based access control", "source_doc_index": 0},
            {
                "fact": "Role for namespace ClusterRole for cluster",
                "source_doc_index": 0,
            },
            {"fact": "RoleBinding binds to subjects", "source_doc_index": 0},
        ],
    },
    {
        "question": "How does Redis clustering work?",
        "documents": [
            {
                "title": "Redis: Cluster",
                "content": "Redis Cluster provides a way to run a Redis installation where data is automatically sharded across multiple Redis nodes. It uses hash slots — there are 16384 hash slots in Redis Cluster. Every node in a Redis Cluster is responsible for a subset of the hash slots. Redis Cluster provides automatic failover when a master node becomes unreachable.",
            },
            {
                "title": "Redis: Sentinel",
                "content": "Redis Sentinel provides high availability for Redis. Sentinel monitors Redis instances, notifies administrators of failures, and performs automatic failover. Sentinel is a separate process from the Redis server.",
            },
            {
                "title": "Redis: Replication",
                "content": "Redis replication allows replica nodes to be exact copies of master nodes. A replica automatically reconnects to the master every time the link breaks and attempts to be an exact copy of it.",
            },
        ],
        "required_facts": [
            {"fact": "data sharded across nodes", "source_doc_index": 0},
            {"fact": "16384 hash slots", "source_doc_index": 0},
            {"fact": "automatic failover", "source_doc_index": 0},
        ],
    },
    {
        "question": "What is the Python logging module's basic architecture?",
        "documents": [
            {
                "title": "Python: logging",
                "content": "The logging module provides a flexible framework for emitting log messages from Python programs. The basic classes are Logger, Handler, Filter, and Formatter. Loggers expose the interface that application code directly uses. Handlers send log records to the appropriate destination. Filters provide fine-grained control. Formatters specify the layout of log records in the final output.",
            },
            {
                "title": "Python: warnings",
                "content": "Warning messages are typically issued in situations where it is useful to alert the user of some condition in a program. The warnings module provides functions to issue warnings and to filter them.",
            },
            {
                "title": "Python: traceback",
                "content": "The traceback module provides a standard interface to extract, format and print stack traces of Python programs. It exactly mimics the behavior of the Python interpreter when it prints a stack trace.",
            },
        ],
        "required_facts": [
            {"fact": "Logger Handler Filter Formatter", "source_doc_index": 0},
            {
                "fact": "Loggers expose interface for application code",
                "source_doc_index": 0,
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# MEDIUM tasks (10): multi-doc synthesis
# ---------------------------------------------------------------------------

_MEDIUM_TASKS: List[Dict[str, Any]] = [
    {
        "question": "Compare RDB and AOF persistence strategies in Redis. When should you use each?",
        "documents": [
            {
                "title": "Redis: RDB Persistence",
                "content": "RDB persistence performs point-in-time snapshots at specified intervals. It produces compact single-file backups, perfect for disaster recovery. RDB maximizes Redis performance since the only work the Redis parent process needs to do is forking. However, RDB is not good if you need to minimize data loss — you might lose several minutes of data if Redis stops working.",
            },
            {
                "title": "Redis: AOF Persistence",
                "content": "AOF logs every write operation. The AOF can be configured to fsync every second (default), every query, or never. With every-second fsync, you lose at most one second of data. The AOF file is append-only, so no seeks or corruption problems. Redis can automatically rewrite the AOF in background when it gets too big.",
            },
            {
                "title": "Redis: Configuration",
                "content": "Redis configuration can be set via redis.conf file or CONFIG SET command at runtime. Key persistence settings: save <seconds> <changes> for RDB, appendonly yes/no for AOF, appendfsync always/everysec/no for AOF sync policy.",
            },
            {
                "title": "Redis: Performance Tuning",
                "content": "For best performance, disable persistence entirely if data loss is acceptable. If persistence is needed, RDB with infrequent saves offers better throughput than AOF. For critical data, use both RDB and AOF together.",
            },
        ],
        "required_facts": [
            {"fact": "RDB creates point-in-time snapshots", "source_doc_index": 0},
            {"fact": "RDB may lose minutes of data", "source_doc_index": 0},
            {"fact": "AOF logs every write operation", "source_doc_index": 1},
            {
                "fact": "AOF loses at most one second with default fsync",
                "source_doc_index": 1,
            },
            {"fact": "use both together for critical data", "source_doc_index": 3},
        ],
    },
    {
        "question": "How do Kubernetes Services and Ingress work together to expose applications?",
        "documents": [
            {
                "title": "K8s: Services",
                "content": "A Service is an abstraction that defines a logical set of Pods and a policy to access them. Service types include ClusterIP (internal only), NodePort (exposes on each node's IP), and LoadBalancer (provisions external load balancer). Services use label selectors to identify target pods.",
            },
            {
                "title": "K8s: Ingress",
                "content": "Ingress exposes HTTP/HTTPS routes from outside the cluster to Services. An Ingress may be configured to give Services externally-reachable URLs, load balance traffic, terminate SSL/TLS, and offer name-based virtual hosting. You need an Ingress controller to satisfy an Ingress.",
            },
            {
                "title": "K8s: Ingress Controllers",
                "content": "An Ingress controller is responsible for fulfilling the Ingress, usually with a load balancer. Popular controllers include NGINX Ingress Controller, Traefik, and HAProxy. Without a controller, Ingress resources have no effect.",
            },
            {
                "title": "K8s: DNS",
                "content": "Kubernetes creates DNS records for Services and Pods. A Service named my-svc in namespace my-ns can be reached at my-svc.my-ns.svc.cluster.local. The DNS server watches the Kubernetes API for new Services.",
            },
        ],
        "required_facts": [
            {"fact": "Service defines logical set of Pods", "source_doc_index": 0},
            {"fact": "ClusterIP NodePort LoadBalancer types", "source_doc_index": 0},
            {"fact": "Ingress exposes HTTP routes externally", "source_doc_index": 1},
            {"fact": "need Ingress controller", "source_doc_index": 2},
        ],
    },
    {
        "question": "Explain PostgreSQL replication: streaming replication vs logical replication.",
        "documents": [
            {
                "title": "PostgreSQL: Streaming Replication",
                "content": "Streaming replication allows a standby server to stay more up-to-date than is possible with file-based log shipping. The standby connects to the primary and receives WAL records as they are generated, without waiting for a WAL file to be filled. Streaming replication is asynchronous by default but can be configured as synchronous.",
            },
            {
                "title": "PostgreSQL: Logical Replication",
                "content": "Logical replication uses a publish/subscribe model. The publisher defines publications, and subscribers define subscriptions. It allows fine-grained control over which tables and operations are replicated. Unlike streaming replication, logical replication can replicate across different major versions.",
            },
            {
                "title": "PostgreSQL: WAL",
                "content": "Write-Ahead Logging (WAL) is the method PostgreSQL uses to ensure data integrity. Changes are first written to a log before being applied to data files. WAL enables both crash recovery and replication.",
            },
            {
                "title": "PostgreSQL: Backup",
                "content": "pg_basebackup makes a binary copy of the database cluster files. It creates a base backup that can be used as a starting point for streaming replication or point-in-time recovery.",
            },
        ],
        "required_facts": [
            {
                "fact": "streaming replication sends WAL records continuously",
                "source_doc_index": 0,
            },
            {
                "fact": "streaming can be synchronous or asynchronous",
                "source_doc_index": 0,
            },
            {"fact": "logical uses publish subscribe model", "source_doc_index": 1},
            {
                "fact": "logical can replicate across major versions",
                "source_doc_index": 1,
            },
        ],
    },
    {
        "question": "How do FastAPI middleware and dependencies differ? When should you use each?",
        "documents": [
            {
                "title": "FastAPI: Middleware",
                "content": "Middleware processes every request before it reaches path operations, and every response before it is sent back. Middleware functions receive the request and a call_next function. Common uses: CORS headers, request timing, authentication checks on all routes. Middleware runs for ALL requests.",
            },
            {
                "title": "FastAPI: Dependencies",
                "content": "Dependencies are declared per-path-operation or per-router using Depends(). They can have their own dependencies (sub-dependencies). Dependencies can yield values (for cleanup), raise exceptions, and access the request. They run only for the specific endpoints that declare them.",
            },
            {
                "title": "FastAPI: Security",
                "content": "FastAPI provides security utilities built on top of dependencies. OAuth2PasswordBearer is a dependency that extracts a token from the Authorization header. You can combine multiple security schemes using dependency injection.",
            },
            {
                "title": "FastAPI: Background Tasks",
                "content": "You can define background tasks to run after returning a response. BackgroundTasks can be declared as a parameter in path operation functions or dependencies.",
            },
        ],
        "required_facts": [
            {"fact": "middleware runs for all requests", "source_doc_index": 0},
            {"fact": "dependencies run per endpoint", "source_doc_index": 1},
            {"fact": "dependencies can have sub-dependencies", "source_doc_index": 1},
            {"fact": "security utilities built on dependencies", "source_doc_index": 2},
        ],
    },
    {
        "question": "How do Python asyncio event loops and tasks coordinate concurrent execution?",
        "documents": [
            {
                "title": "Python: asyncio Event Loop",
                "content": "The event loop runs asynchronous tasks and callbacks, performs network IO operations, and runs subprocesses. asyncio.run() creates a new event loop, runs the given coroutine, and closes the loop. Only one event loop can run per thread. The event loop uses cooperative multitasking — tasks must yield control voluntarily.",
            },
            {
                "title": "Python: asyncio Tasks",
                "content": "Tasks wrap coroutines and schedule them on the event loop. asyncio.create_task() schedules a coroutine for concurrent execution. asyncio.gather() runs multiple awaitables concurrently and returns results when all complete. Tasks can be cancelled using task.cancel().",
            },
            {
                "title": "Python: asyncio Synchronization",
                "content": "asyncio provides Lock, Event, Condition, and Semaphore for coordinating concurrent tasks. Unlike threading primitives, these are not thread-safe and must be used within the same event loop.",
            },
            {
                "title": "Python: concurrent.futures",
                "content": "The concurrent.futures module provides ThreadPoolExecutor and ProcessPoolExecutor. asyncio can integrate with these using loop.run_in_executor() to run blocking functions without blocking the event loop.",
            },
        ],
        "required_facts": [
            {
                "fact": "cooperative multitasking tasks yield control",
                "source_doc_index": 0,
            },
            {
                "fact": "create_task schedules concurrent execution",
                "source_doc_index": 1,
            },
            {
                "fact": "gather runs multiple awaitables concurrently",
                "source_doc_index": 1,
            },
            {"fact": "run_in_executor for blocking functions", "source_doc_index": 3},
        ],
    },
    {
        "question": "How does nginx load balancing interact with SSL termination?",
        "documents": [
            {
                "title": "nginx: Load Balancing",
                "content": "nginx distributes traffic using upstream blocks with methods: round-robin (default), least_conn, ip_hash, and hash. Health checks can detect failed backends. The max_fails and fail_timeout parameters control when a server is marked unavailable.",
            },
            {
                "title": "nginx: SSL/TLS Termination",
                "content": "SSL termination at nginx means nginx handles TLS handshakes and decryption, then forwards plain HTTP to backend servers. This offloads CPU-intensive cryptographic operations from application servers. Configure with ssl_certificate and ssl_certificate_key in the server block.",
            },
            {
                "title": "nginx: Proxy Settings",
                "content": "proxy_set_header X-Forwarded-Proto $scheme passes the original protocol to backends. proxy_set_header X-Real-IP $remote_addr passes the client's real IP. These headers are important when SSL is terminated at the proxy layer.",
            },
            {
                "title": "nginx: HTTP/2",
                "content": "nginx supports HTTP/2 with the http2 parameter on the listen directive. HTTP/2 enables multiplexing, header compression, and server push. HTTP/2 requires TLS in most browsers.",
            },
        ],
        "required_facts": [
            {
                "fact": "upstream blocks with round-robin least_conn ip_hash",
                "source_doc_index": 0,
            },
            {
                "fact": "SSL termination offloads crypto from backends",
                "source_doc_index": 1,
            },
            {
                "fact": "X-Forwarded-Proto passes original protocol",
                "source_doc_index": 2,
            },
        ],
    },
    {
        "question": "Compare PostgreSQL B-tree and GIN indexes. When is each appropriate?",
        "documents": [
            {
                "title": "PostgreSQL: B-tree Indexes",
                "content": "B-tree indexes are the default index type. They can handle equality and range queries on data that can be sorted. B-tree indexes work with all data types that have a well-defined ordering. They support queries with operators <, <=, =, >=, >, BETWEEN, IN, IS NULL, and IS NOT NULL.",
            },
            {
                "title": "PostgreSQL: GIN Indexes",
                "content": "GIN (Generalized Inverted Index) indexes are designed for composite values where queries search for elements within the composite value. Common uses: full-text search (tsvector), JSONB containment (@>), and array operations (&&, @>). GIN indexes are slower to build than B-tree but faster for lookups on composite types.",
            },
            {
                "title": "PostgreSQL: Index Maintenance",
                "content": "Indexes consume storage and slow down writes. Each INSERT/UPDATE/DELETE must update every index on the table. PostgreSQL's HOT (Heap Only Tuple) updates can avoid index updates when indexed columns are not modified. Use REINDEX to rebuild corrupted indexes.",
            },
            {
                "title": "PostgreSQL: Query Planning",
                "content": "The query planner decides whether to use an index based on table statistics. ANALYZE updates these statistics. A sequential scan may be chosen over an index scan if the query will access a large portion of the table.",
            },
        ],
        "required_facts": [
            {
                "fact": "B-tree handles equality and range queries",
                "source_doc_index": 0,
            },
            {
                "fact": "GIN for composite values like full-text JSONB arrays",
                "source_doc_index": 1,
            },
            {"fact": "GIN slower to build faster for lookups", "source_doc_index": 1},
            {"fact": "indexes slow down writes", "source_doc_index": 2},
        ],
    },
    {
        "question": "How do Kubernetes pod scheduling and resource management work together?",
        "documents": [
            {
                "title": "K8s: Scheduling",
                "content": "The scheduler assigns Pods to Nodes based on resource requirements, affinity/anti-affinity rules, taints and tolerations, and topology spread constraints. Pods can specify nodeSelector to constrain which nodes they can run on. The scheduler filters nodes that don't meet requirements, then ranks remaining nodes.",
            },
            {
                "title": "K8s: Resource Management",
                "content": "Containers can specify CPU and memory requests and limits. Requests are what the container is guaranteed. Limits are the maximum allowed. If a container exceeds its memory limit, it is OOM-killed. CPU limits are enforced via CFS throttling.",
            },
            {
                "title": "K8s: Priority and Preemption",
                "content": "PriorityClasses define pod priority. Higher-priority pods can preempt (evict) lower-priority pods when no node has enough resources. The preempted pods are given a graceful termination period.",
            },
            {
                "title": "K8s: Horizontal Pod Autoscaler",
                "content": "HPA automatically scales the number of pod replicas based on observed CPU utilization, memory usage, or custom metrics. It queries the metrics API every 15 seconds by default.",
            },
        ],
        "required_facts": [
            {
                "fact": "scheduler uses affinity taints nodeSelector",
                "source_doc_index": 0,
            },
            {
                "fact": "requests are guaranteed limits are maximum",
                "source_doc_index": 1,
            },
            {"fact": "OOM-killed if memory limit exceeded", "source_doc_index": 1},
            {"fact": "priority classes enable preemption", "source_doc_index": 2},
        ],
    },
    {
        "question": "How do FastAPI WebSockets differ from regular HTTP endpoints?",
        "documents": [
            {
                "title": "FastAPI: WebSocket",
                "content": "FastAPI supports WebSocket endpoints using @app.websocket() decorator. Unlike HTTP, WebSocket provides full-duplex communication — both client and server can send messages at any time. The connection remains open until explicitly closed. You use await websocket.accept() to accept the connection, and await websocket.receive_text() / await websocket.send_text() for messaging.",
            },
            {
                "title": "FastAPI: HTTP Endpoints",
                "content": "Regular HTTP endpoints use @app.get(), @app.post(), etc. Each request creates a new connection, the server processes it, and returns a response. HTTP is stateless — each request is independent. FastAPI automatically generates OpenAPI documentation for HTTP endpoints.",
            },
            {
                "title": "FastAPI: Testing",
                "content": "TestClient from Starlette supports testing both HTTP and WebSocket endpoints. For WebSocket testing, use 'with client.websocket_connect(\"/ws\") as ws:' to establish a test connection.",
            },
            {
                "title": "FastAPI: Events",
                "content": "Lifespan events allow running code on application startup and shutdown. Use the lifespan parameter with an async context manager. This replaces the deprecated on_event decorator.",
            },
        ],
        "required_facts": [
            {
                "fact": "WebSocket provides full-duplex communication",
                "source_doc_index": 0,
            },
            {"fact": "connection remains open until closed", "source_doc_index": 0},
            {
                "fact": "HTTP is stateless each request independent",
                "source_doc_index": 1,
            },
            {
                "fact": "OpenAPI docs generated for HTTP not WebSocket",
                "source_doc_index": 1,
            },
        ],
    },
    {
        "question": "Explain Redis memory eviction policies and when to use maxmemory.",
        "documents": [
            {
                "title": "Redis: Memory Management",
                "content": "When maxmemory is set and the limit is reached, Redis applies an eviction policy. volatile-lru removes least recently used keys with an expire set. allkeys-lru removes any LRU key. volatile-ttl removes keys with shortest TTL. noeviction returns errors on write commands when memory is full.",
            },
            {
                "title": "Redis: Configuration",
                "content": "Set maxmemory in redis.conf or via CONFIG SET maxmemory <bytes>. Without maxmemory, Redis on 64-bit systems has no memory limit and will use all available RAM. On 32-bit systems, there is an implicit 3GB limit.",
            },
            {
                "title": "Redis: Data Types",
                "content": "Redis supports strings, lists, sets, sorted sets, hashes, streams, and more. Each data type has internal encoding optimizations. Small sets use ziplist encoding, larger sets use hashtable encoding.",
            },
            {
                "title": "Redis: Monitoring",
                "content": "INFO memory command shows used_memory, used_memory_rss, mem_fragmentation_ratio, and evicted_keys count. A high fragmentation ratio indicates memory fragmentation. MEMORY DOCTOR provides recommendations.",
            },
        ],
        "required_facts": [
            {
                "fact": "volatile-lru removes LRU keys with expire",
                "source_doc_index": 0,
            },
            {"fact": "noeviction returns errors on writes", "source_doc_index": 0},
            {"fact": "without maxmemory uses all available RAM", "source_doc_index": 1},
            {
                "fact": "INFO memory shows usage and fragmentation",
                "source_doc_index": 3,
            },
        ],
    },
]

# ---------------------------------------------------------------------------
# HARD tasks (10): multi-doc reasoning with distractors
# ---------------------------------------------------------------------------

_HARD_TASKS: List[Dict[str, Any]] = [
    {
        "question": "Design a high-availability PostgreSQL setup with both streaming and logical replication. What are the trade-offs?",
        "documents": [
            {
                "title": "PostgreSQL: Streaming Replication",
                "content": "Streaming replication transmits WAL records from primary to standbys in real-time. Synchronous mode guarantees no data loss but adds write latency (typically 1-5ms per commit). Asynchronous mode has minimal latency impact but may lose recent transactions on failover. A standby can serve read-only queries.",
            },
            {
                "title": "PostgreSQL: Logical Replication",
                "content": "Logical replication decodes WAL into logical changes and applies them on subscribers. It supports selective table replication, cross-version upgrades, and publishing to multiple subscribers. It cannot replicate DDL, sequences, or large objects. Logical replication has higher CPU overhead than streaming.",
            },
            {
                "title": "PostgreSQL: Connection Pooling",
                "content": "PgBouncer or Pgpool-II can pool connections to reduce overhead. PgBouncer supports transaction-mode pooling where connections are returned to the pool after each transaction. This is essential for applications with many short-lived connections.",
            },
            {
                "title": "PostgreSQL: Partitioning",
                "content": "Table partitioning divides a large table into smaller physical pieces. Range partitioning and list partitioning are the most common. Partition pruning eliminates irrelevant partitions during query planning. Partitioning can improve both query performance and maintenance operations like VACUUM.",
            },
            {
                "title": "PostgreSQL: pg_stat_replication",
                "content": "The pg_stat_replication view shows one row per WAL sender process, with information about replication state, sent_lsn, write_lsn, flush_lsn, and replay_lsn. The difference between sent_lsn and replay_lsn indicates replication lag.",
            },
            {
                "title": "PostgreSQL: Failover",
                "content": "pg_promote() promotes a standby to primary. Tools like Patroni or repmgr automate failover with consensus-based leader election. After failover, old primary must be rebuilt as a standby using pg_rewind or pg_basebackup.",
            },
        ],
        "required_facts": [
            {
                "fact": "synchronous streaming guarantees no data loss adds latency",
                "source_doc_index": 0,
            },
            {"fact": "standby serves read-only queries", "source_doc_index": 0},
            {"fact": "logical cannot replicate DDL sequences", "source_doc_index": 1},
            {"fact": "logical has higher CPU overhead", "source_doc_index": 1},
            {"fact": "Patroni or repmgr for automated failover", "source_doc_index": 5},
            {
                "fact": "replication lag via sent_lsn vs replay_lsn",
                "source_doc_index": 4,
            },
        ],
    },
    {
        "question": "How would you implement a zero-downtime Kubernetes deployment with proper health checks and rollback?",
        "documents": [
            {
                "title": "K8s: Rolling Updates",
                "content": "Deployments support rolling updates via maxSurge and maxUnavailable parameters. maxSurge controls how many extra pods can be created. maxUnavailable controls how many pods can be unavailable during update. Setting maxUnavailable to 0 and maxSurge to 1 ensures no downtime but slower rollout.",
            },
            {
                "title": "K8s: Health Probes",
                "content": "livenessProbe restarts containers that are deadlocked. readinessProbe removes pods from Service endpoints when not ready. startupProbe disables liveness/readiness checks until the app has started. All support httpGet, tcpSocket, exec, and gRPC probe types. initialDelaySeconds, periodSeconds, and failureThreshold control timing.",
            },
            {
                "title": "K8s: Rollback",
                "content": "kubectl rollout undo deployment/<name> reverts to the previous revision. kubectl rollout history shows all revisions. minReadySeconds specifies how long a new pod should be ready before it's considered available. progressDeadlineSeconds sets the maximum time for a deployment to make progress.",
            },
            {
                "title": "K8s: Pod Disruption Budgets",
                "content": "PodDisruptionBudget (PDB) limits the number of pods of a replicated application that are down simultaneously from voluntary disruptions. It specifies either minAvailable or maxUnavailable.",
            },
            {
                "title": "K8s: ConfigMaps",
                "content": "ConfigMaps decouple configuration from container images. They can be consumed as environment variables, command-line arguments, or configuration files in a volume. Changes to ConfigMaps do not trigger pod restarts by default.",
            },
            {
                "title": "K8s: Resource Quotas",
                "content": "ResourceQuota constrains aggregate resource consumption per namespace. It can limit total CPU, memory, storage, and object counts. LimitRange sets default limits for containers that don't specify their own.",
            },
        ],
        "required_facts": [
            {
                "fact": "maxSurge and maxUnavailable control rolling update",
                "source_doc_index": 0,
            },
            {
                "fact": "readinessProbe removes from endpoints when not ready",
                "source_doc_index": 1,
            },
            {
                "fact": "startupProbe disables other probes until started",
                "source_doc_index": 1,
            },
            {
                "fact": "rollout undo reverts to previous revision",
                "source_doc_index": 2,
            },
            {
                "fact": "PodDisruptionBudget limits voluntary disruptions",
                "source_doc_index": 3,
            },
        ],
    },
    {
        "question": "Design a Redis caching layer with persistence guarantees. How do you handle cache warming and eviction?",
        "documents": [
            {
                "title": "Redis: Cache Patterns",
                "content": "Cache-aside (lazy loading): application checks cache first, on miss reads from database and populates cache. Write-through: application writes to both cache and database simultaneously. Write-behind: application writes to cache, which asynchronously writes to database. Each pattern has different consistency guarantees.",
            },
            {
                "title": "Redis: RDB + AOF",
                "content": "Using both RDB and AOF together provides the strongest persistence guarantees. On restart, Redis uses AOF to reconstruct data (it's more complete). RDB serves as a compact backup. Configure with 'save 900 1' for RDB and 'appendonly yes' with 'appendfsync everysec' for AOF.",
            },
            {
                "title": "Redis: Pipeline",
                "content": "Pipelining sends multiple commands without waiting for replies. This reduces round-trip time from one RTT per command to one RTT per batch. MULTI/EXEC provides atomic transactions. Pipeline + MULTI combines batching with atomicity.",
            },
            {
                "title": "Redis: Memory Management",
                "content": "allkeys-lfu evicts least frequently used keys. volatile-lfu evicts LFU keys with TTL set. LFU is better than LRU for caches with hot/cold key patterns. Configure with maxmemory-policy. Redis 4.0+ supports LFU with configurable decay time.",
            },
            {
                "title": "Redis: Pub/Sub",
                "content": "PUBLISH/SUBSCRIBE allows message passing between Redis clients. Messages are fire-and-forget — if no subscriber is listening, the message is lost. For durable messaging, use Redis Streams instead.",
            },
            {
                "title": "Redis: Keyspace Notifications",
                "content": "Redis can emit notifications for key events (set, del, expired, evicted). Configure with notify-keyspace-events. Applications can subscribe to these events for cache invalidation or monitoring.",
            },
        ],
        "required_facts": [
            {
                "fact": "cache-aside checks cache first reads DB on miss",
                "source_doc_index": 0,
            },
            {
                "fact": "write-through writes to both simultaneously",
                "source_doc_index": 0,
            },
            {
                "fact": "RDB plus AOF together for strongest persistence",
                "source_doc_index": 1,
            },
            {
                "fact": "LFU better than LRU for hot cold patterns",
                "source_doc_index": 3,
            },
            {
                "fact": "keyspace notifications for cache invalidation",
                "source_doc_index": 5,
            },
        ],
    },
    {
        "question": "How would you build a production FastAPI application with proper middleware, dependency injection, and error handling?",
        "documents": [
            {
                "title": "FastAPI: Middleware Stack",
                "content": "Middleware executes in order of registration. Common middleware stack: CORSMiddleware (CORS headers), TrustedHostMiddleware (host header validation), GZipMiddleware (response compression). Custom middleware can measure request duration, add request IDs, and handle rate limiting. Middleware exceptions bypass exception handlers.",
            },
            {
                "title": "FastAPI: Dependency Injection",
                "content": "Dependencies can be scoped to path operations, routers, or the entire app. Use yield dependencies for setup/teardown (e.g., database sessions). Dependencies form a DAG — FastAPI resolves them in the correct order. Sub-dependencies are cached per-request by default.",
            },
            {
                "title": "FastAPI: Exception Handling",
                "content": "HTTPException returns HTTP error responses. Custom exception handlers can be registered with @app.exception_handler(). RequestValidationError handles Pydantic validation failures. Override the default handlers to customize error response format. Unhandled exceptions return 500 with no details in production.",
            },
            {
                "title": "FastAPI: Authentication",
                "content": "OAuth2PasswordBearer extracts bearer tokens. HTTPBearer validates Authorization headers. Security schemes appear in OpenAPI docs. Combine with dependencies for role-based access control.",
            },
            {
                "title": "FastAPI: Static Files",
                "content": "StaticFiles middleware serves static files from a directory. Mount with app.mount('/static', StaticFiles(directory='static'), name='static'). Supports HTML, CSS, JS, and other file types.",
            },
            {
                "title": "FastAPI: Response Models",
                "content": "response_model parameter filters output to match the declared model. response_model_exclude_unset removes default values from response. This prevents leaking internal fields and ensures consistent API contracts.",
            },
        ],
        "required_facts": [
            {
                "fact": "middleware exceptions bypass exception handlers",
                "source_doc_index": 0,
            },
            {"fact": "yield dependencies for setup teardown", "source_doc_index": 1},
            {"fact": "sub-dependencies cached per request", "source_doc_index": 1},
            {
                "fact": "RequestValidationError for Pydantic failures",
                "source_doc_index": 2,
            },
            {"fact": "response_model filters output", "source_doc_index": 5},
        ],
    },
    {
        "question": "Design a secure Kubernetes cluster network architecture with RBAC, network policies, and pod security.",
        "documents": [
            {
                "title": "K8s: Network Policies",
                "content": "Network policies use label selectors to control pod-to-pod traffic. A default-deny policy blocks all ingress traffic to pods in a namespace. Egress policies can restrict outbound traffic. Network policies require a CNI plugin that supports them (Calico, Cilium, Weave Net). Policies are additive — if any policy allows traffic, it is allowed.",
            },
            {
                "title": "K8s: RBAC",
                "content": "Use least-privilege principle: create specific Roles with minimal verbs (get, list, watch, create, update, delete). Avoid ClusterRoleBinding to cluster-admin. Use namespaced RoleBindings when possible. Audit RBAC permissions with 'kubectl auth can-i --list'. ServiceAccounts should have automountServiceAccountToken: false when not needed.",
            },
            {
                "title": "K8s: Pod Security Standards",
                "content": "Pod Security Admission enforces Privileged (unrestricted), Baseline (minimally restrictive), and Restricted (hardened) profiles. Restricted profile prohibits running as root, requires read-only root filesystem, drops ALL capabilities, and requires seccomp profile. Apply per-namespace with labels.",
            },
            {
                "title": "K8s: Secrets",
                "content": "Secrets store sensitive data like passwords and tokens. By default, Secrets are stored unencrypted in etcd. Enable encryption at rest using EncryptionConfiguration. Prefer external secret stores (Vault, AWS Secrets Manager) with CSI driver or external-secrets operator.",
            },
            {
                "title": "K8s: Admission Controllers",
                "content": "Admission controllers intercept API requests after authentication but before persistence. ValidatingWebhookConfiguration rejects non-compliant resources. MutatingWebhookConfiguration can modify resources (e.g., inject sidecars, add labels). OPA Gatekeeper or Kyverno provide policy-as-code.",
            },
            {
                "title": "K8s: Namespaces",
                "content": "Namespaces provide scope for names and a mechanism to divide cluster resources. Use namespaces to separate environments (dev, staging, prod) or teams. ResourceQuotas and LimitRanges are applied per-namespace.",
            },
        ],
        "required_facts": [
            {"fact": "default-deny policy blocks all ingress", "source_doc_index": 0},
            {"fact": "policies are additive", "source_doc_index": 0},
            {"fact": "least privilege with minimal verbs", "source_doc_index": 1},
            {"fact": "automountServiceAccountToken false", "source_doc_index": 1},
            {
                "fact": "restricted profile prohibits root drops capabilities",
                "source_doc_index": 2,
            },
            {"fact": "secrets unencrypted in etcd by default", "source_doc_index": 3},
        ],
    },
    {
        "question": "How would you implement comprehensive Python logging with structured output, rotation, and monitoring integration?",
        "documents": [
            {
                "title": "Python: logging Configuration",
                "content": "dictConfig() provides the most flexible configuration. Loggers form a hierarchy based on dot-separated names. The root logger catches all unhandled log records. Each logger can have multiple handlers with different levels. Propagation sends records up the hierarchy — set propagate=False to prevent duplicate logs.",
            },
            {
                "title": "Python: logging Handlers",
                "content": "RotatingFileHandler rotates logs when they reach a size limit (maxBytes, backupCount). TimedRotatingFileHandler rotates based on time intervals. SocketHandler sends records to a network socket. QueueHandler + QueueListener enable non-blocking logging with a separate thread for I/O.",
            },
            {
                "title": "Python: logging Formatters",
                "content": "Custom formatters can output JSON for structured logging. Use LogRecord attributes: %(asctime)s, %(name)s, %(levelname)s, %(message)s, %(pathname)s, %(lineno)d. python-json-logger library provides JsonFormatter. Include request IDs and trace context for distributed tracing.",
            },
            {
                "title": "Python: logging Filters",
                "content": "Filters can modify or suppress log records. A filter's filter() method returns True to allow the record. Filters can add extra fields to records (e.g., user_id, request_id). Attach filters to loggers or handlers.",
            },
            {
                "title": "Python: warnings Integration",
                "content": "logging.captureWarnings(True) redirects Python warnings to the logging system. This allows consistent handling of both warnings and log messages through the same pipeline.",
            },
            {
                "title": "Python: contextvars",
                "content": "contextvars provides context-local storage for async code. ContextVar objects store per-task values. Unlike threading.local(), contextvars works correctly with asyncio. Use it to propagate request IDs through async call chains.",
            },
        ],
        "required_facts": [
            {"fact": "dictConfig for flexible configuration", "source_doc_index": 0},
            {"fact": "propagate False prevents duplicate logs", "source_doc_index": 0},
            {
                "fact": "RotatingFileHandler with maxBytes backupCount",
                "source_doc_index": 1,
            },
            {"fact": "QueueHandler for non-blocking logging", "source_doc_index": 1},
            {"fact": "JSON formatters for structured logging", "source_doc_index": 2},
            {
                "fact": "contextvars for request ID propagation in async",
                "source_doc_index": 5,
            },
        ],
    },
    {
        "question": "Explain how to optimize PostgreSQL query performance using EXPLAIN ANALYZE, indexes, and configuration tuning.",
        "documents": [
            {
                "title": "PostgreSQL: EXPLAIN ANALYZE",
                "content": "EXPLAIN ANALYZE actually runs the query and shows real execution times alongside estimates. Key metrics: actual time (startup..total), rows (estimated vs actual), loops. Bitmap Heap Scan indicates the planner chose an index but needs to recheck. Sort Method shows if sort spilled to disk. Buffers option shows shared/local hit/read counts for I/O analysis.",
            },
            {
                "title": "PostgreSQL: Index Types",
                "content": "B-tree for equality/range (default). Hash for equality-only (rarely useful). GiST for geometric, full-text, and range types. GIN for full-text search, JSONB, arrays. BRIN for large tables with natural ordering (timestamps). Partial indexes (WHERE clause) reduce index size. Expression indexes allow indexing computed values.",
            },
            {
                "title": "PostgreSQL: Configuration",
                "content": "shared_buffers: typically 25% of system RAM. effective_cache_size: total expected filesystem cache (50-75% of RAM). work_mem: per-operation sort/hash memory. maintenance_work_mem: for VACUUM, CREATE INDEX. random_page_cost: lower for SSDs (1.1 vs 4.0 default). Setting these correctly can improve query plans dramatically.",
            },
            {
                "title": "PostgreSQL: Table Statistics",
                "content": "ANALYZE collects statistics about column value distributions. default_statistics_target controls granularity (default 100, increase for skewed data). pg_stats view shows most common values, histogram bounds, null fraction, and n_distinct. Stale statistics lead to poor query plans.",
            },
            {
                "title": "PostgreSQL: Partitioning",
                "content": "Partition pruning eliminates irrelevant partitions during planning. Constraint exclusion achieves similar results for inherited tables. Partitioning helps when tables exceed available memory or when queries consistently filter on the partition key.",
            },
            {
                "title": "PostgreSQL: Lock Monitoring",
                "content": "pg_stat_activity shows currently running queries. pg_locks shows held and awaited locks. Lock contention can cause query timeouts. Use statement_timeout to prevent runaway queries. pg_stat_statements tracks query performance over time.",
            },
        ],
        "required_facts": [
            {
                "fact": "EXPLAIN ANALYZE shows real execution times",
                "source_doc_index": 0,
            },
            {"fact": "Buffers option shows IO hit read counts", "source_doc_index": 0},
            {
                "fact": "BRIN for large tables with natural ordering",
                "source_doc_index": 1,
            },
            {"fact": "partial indexes reduce index size", "source_doc_index": 1},
            {"fact": "shared_buffers 25% of RAM", "source_doc_index": 2},
            {"fact": "random_page_cost lower for SSDs", "source_doc_index": 2},
        ],
    },
    {
        "question": "How would you implement a robust nginx configuration for a microservices architecture with rate limiting, caching, and health checks?",
        "documents": [
            {
                "title": "nginx: Rate Limiting",
                "content": "limit_req_zone defines a shared memory zone for rate limiting. limit_req applies the limit to a location. burst parameter allows temporary spikes. nodelay processes burst requests immediately rather than queuing. limit_req_status sets the HTTP status code for rejected requests (default 503). Use $binary_remote_addr for per-IP limiting.",
            },
            {
                "title": "nginx: Caching",
                "content": "proxy_cache_path defines the cache directory, zone size, and eviction settings. proxy_cache activates caching for a location. proxy_cache_valid sets cache duration per status code. proxy_cache_bypass allows skipping cache based on conditions. proxy_cache_use_stale serves stale content during backend errors or updates.",
            },
            {
                "title": "nginx: Health Checks",
                "content": "Passive health checks mark backends as unavailable after max_fails within fail_timeout period. Active health checks (nginx Plus or third-party modules) send periodic requests to a health endpoint. health_check interval=5s passes=3 fails=2 configures active checks.",
            },
            {
                "title": "nginx: Load Balancing Advanced",
                "content": "upstream blocks support server weights for proportional distribution. backup servers receive traffic only when all primary servers are unavailable. least_conn with weights combines connection-aware and weighted distribution. keepalive directive maintains persistent connections to upstreams.",
            },
            {
                "title": "nginx: Logging",
                "content": "access_log and error_log configure logging. log_format defines custom log formats. access_log can use variables for conditional logging. Buffer and flush parameters control I/O performance. JSON log format enables structured log processing.",
            },
            {
                "title": "nginx: Security Headers",
                "content": "add_header X-Frame-Options DENY prevents clickjacking. add_header Content-Security-Policy restricts resource loading. add_header Strict-Transport-Security enables HSTS. add_header X-Content-Type-Options nosniff prevents MIME sniffing.",
            },
        ],
        "required_facts": [
            {"fact": "limit_req_zone with binary_remote_addr", "source_doc_index": 0},
            {"fact": "burst and nodelay for spike handling", "source_doc_index": 0},
            {
                "fact": "proxy_cache_use_stale serves during errors",
                "source_doc_index": 1,
            },
            {
                "fact": "passive checks use max_fails fail_timeout",
                "source_doc_index": 2,
            },
            {"fact": "backup servers for failover", "source_doc_index": 3},
        ],
    },
    {
        "question": "Design a Redis-based distributed locking system with proper expiration, retry logic, and fencing tokens.",
        "documents": [
            {
                "title": "Redis: Distributed Locks (Redlock)",
                "content": "SET resource_name my_random_value NX PX 30000 acquires a lock atomically. NX ensures only-if-not-exists. PX sets millisecond expiry. The random value is used for safe release: only delete if the current value matches (use Lua script for atomicity). Redlock algorithm acquires locks on N/2+1 independent Redis instances for fault tolerance.",
            },
            {
                "title": "Redis: Lua Scripting",
                "content": "EVAL runs Lua scripts atomically on the server. Scripts can read and write multiple keys atomically. Use EVALSHA with script caching for performance. Lua scripts block other commands during execution — keep them short. Scripts have access to redis.call() and redis.pcall() functions.",
            },
            {
                "title": "Redis: Pub/Sub",
                "content": "SUBSCRIBE/PUBLISH enables real-time messaging. Channel-based messaging is fire-and-forget. Pattern subscriptions (PSUBSCRIBE) match multiple channels. Pub/Sub does not persist messages. Use Redis Streams for durable messaging with consumer groups.",
            },
            {
                "title": "Redis: Transactions",
                "content": "MULTI/EXEC executes commands atomically. WATCH provides optimistic locking — if a watched key changes before EXEC, the transaction is aborted. Transactions do not support rollback — all or nothing execution. DISCARD cancels a transaction.",
            },
            {
                "title": "Redis: Cluster",
                "content": "In Redis Cluster, locks must account for hash slot assignment. Keys in the same slot are on the same node. Use hash tags {resource} to control slot assignment. During failover, locks may be lost if async replication hasn't caught up.",
            },
            {
                "title": "Redis: Monitoring",
                "content": "SLOWLOG records queries exceeding a time threshold. CLIENT LIST shows connected clients. MONITOR streams all commands received — use sparingly as it impacts performance. INFO commandstats shows per-command statistics.",
            },
        ],
        "required_facts": [
            {
                "fact": "SET NX PX for atomic lock acquisition with expiry",
                "source_doc_index": 0,
            },
            {
                "fact": "random value for safe release with Lua script",
                "source_doc_index": 0,
            },
            {"fact": "Redlock on N/2+1 instances", "source_doc_index": 0},
            {"fact": "Lua scripts execute atomically", "source_doc_index": 1},
            {"fact": "WATCH for optimistic locking", "source_doc_index": 3},
            {"fact": "cluster failover may lose locks", "source_doc_index": 4},
        ],
    },
    {
        "question": "How do you implement a complete observability stack for a Python asyncio application with logging, tracing, and metrics?",
        "documents": [
            {
                "title": "Python: Structured Logging",
                "content": "python-json-logger outputs JSON log records. structlog provides contextualized logging with processors. Both integrate with the standard logging module. Use contextvars to propagate trace IDs through async call chains. Log at structured fields: service, environment, trace_id, span_id, user_id, duration_ms.",
            },
            {
                "title": "Python: OpenTelemetry",
                "content": "opentelemetry-api provides the Tracer and Meter interfaces. opentelemetry-sdk implements them. TracerProvider creates Tracers. Spans represent operations with start/end times, attributes, and events. Context propagation across async boundaries uses contextvars. Exporters send data to Jaeger, Zipkin, or OTLP collectors.",
            },
            {
                "title": "Python: Prometheus Metrics",
                "content": "prometheus_client provides Counter, Gauge, Histogram, and Summary metric types. Counter only goes up (request counts, error counts). Histogram tracks value distributions with configurable buckets. start_http_server() exposes /metrics endpoint. Use labels for dimensions (method, path, status_code).",
            },
            {
                "title": "Python: asyncio Instrumentation",
                "content": "asyncio.Task has get_name()/set_name() for identification. Task groups (asyncio.TaskGroup) manage related tasks. loop.slow_callback_duration controls slow callback warnings. asyncio debug mode logs coroutines that take too long. Custom task factories can inject tracing context.",
            },
            {
                "title": "Python: Health Checks",
                "content": "Implement /healthz and /readyz endpoints. Health checks should verify database connectivity, cache availability, and external service reachability. Use timeouts to prevent health check hangs. Separate liveness (is the process alive?) from readiness (can it serve traffic?).",
            },
            {
                "title": "Python: Error Tracking",
                "content": "Sentry SDK captures exceptions with full stack traces and context. breadcrumbs track events leading to an error. Integrations auto-instrument popular frameworks. Set sample_rate to control volume. tags and extra context help with debugging.",
            },
        ],
        "required_facts": [
            {
                "fact": "structlog or json-logger for structured logging",
                "source_doc_index": 0,
            },
            {"fact": "contextvars for trace ID propagation", "source_doc_index": 0},
            {
                "fact": "OpenTelemetry Spans with attributes and events",
                "source_doc_index": 1,
            },
            {"fact": "Prometheus Counter Gauge Histogram types", "source_doc_index": 2},
            {"fact": "separate liveness from readiness checks", "source_doc_index": 4},
            {"fact": "Sentry captures exceptions with context", "source_doc_index": 5},
        ],
    },
]


class DocQADataset(DatasetProvider):
    """30 document-grounded QA tasks."""

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: str = "test",
        seed: Optional[int] = None,
    ) -> None:
        all_tasks = _EASY_TASKS + _MEDIUM_TASKS + _HARD_TASKS
        difficulties = (
            ["easy"] * len(_EASY_TASKS)
            + ["medium"] * len(_MEDIUM_TASKS)
            + ["hard"] * len(_HARD_TASKS)
        )

        paired = list(zip(all_tasks, difficulties))
        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(paired)

        if max_samples is not None:
            paired = paired[:max_samples]

        self._records: List[EvalRecord] = []
        for idx, (task, diff) in enumerate(paired):
            doc_listing = "\n\n".join(
                f"### Document {i + 1}: {doc['title']}\n{doc['content']}"
                for i, doc in enumerate(task["documents"])
            )

            prompt = _PROMPT_TEMPLATE.format(
                question=task["question"],
                documents=doc_listing,
            )

            # Build reference from required facts
            ref_parts = [f["fact"] for f in task["required_facts"]]

            self._records.append(
                EvalRecord(
                    record_id=f"doc-qa-{idx:03d}",
                    problem=prompt,
                    reference="; ".join(ref_parts),
                    category="agentic",
                    subject=diff,
                    metadata={
                        "question": task["question"],
                        "documents": task["documents"],
                        "required_facts": task["required_facts"],
                    },
                )
            )

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


__all__ = ["DocQADataset"]
