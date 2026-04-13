"""
MiroFish Backend - Flask应用工厂
"""

import os
import warnings

# 抑制 multiprocessing resource_tracker 的警告（来自第三方库如 transformers）
# 需要在所有其他导入之前设置
warnings.filterwarnings("ignore", message=".*resource_tracker.*")

from flask import Flask, request, send_from_directory
from flask_cors import CORS

from .config import Config
from .utils.logger import setup_logger, get_logger


def _resolve_static_dir():
    """解析前端静态资源目录（构建后的 frontend/dist）"""
    # 允许通过环境变量覆盖（Docker/Railway 场景）
    env_dir = os.environ.get('FRONTEND_DIST_DIR')
    if env_dir and os.path.isdir(env_dir):
        return env_dir
    # 默认：相对于 backend/app/__init__.py -> ../../frontend/dist
    default_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'dist')
    )
    return default_dir


def create_app(config_class=Config):
    """Flask应用工厂函数"""
    static_dir = _resolve_static_dir()
    app = Flask(
        __name__,
        static_folder=static_dir,
        static_url_path='',
    )
    app.config.from_object(config_class)
    
    # 设置JSON编码：确保中文直接显示（而不是 \uXXXX 格式）
    # Flask >= 2.3 使用 app.json.ensure_ascii，旧版本使用 JSON_AS_ASCII 配置
    if hasattr(app, 'json') and hasattr(app.json, 'ensure_ascii'):
        app.json.ensure_ascii = False
    
    # 设置日志
    logger = setup_logger('mirofish')
    
    # 只在 reloader 子进程中打印启动信息（避免 debug 模式下打印两次）
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    debug_mode = app.config.get('DEBUG', False)
    should_log_startup = not debug_mode or is_reloader_process
    
    if should_log_startup:
        logger.info("=" * 50)
        logger.info("MiroFish Backend 启动中...")
        logger.info("=" * 50)
    
    # 启用CORS
    CORS(app, resources={r"/api/*": {"origins": "*"}})
    
    # 注册模拟进程清理函数（确保服务器关闭时终止所有模拟进程）
    from .services.simulation_runner import SimulationRunner
    SimulationRunner.register_cleanup()
    if should_log_startup:
        logger.info("已注册模拟进程清理函数")
    
    # 请求日志中间件
    @app.before_request
    def log_request():
        logger = get_logger('mirofish.request')
        logger.debug(f"请求: {request.method} {request.path}")
        if request.content_type and 'json' in request.content_type:
            logger.debug(f"请求体: {request.get_json(silent=True)}")
    
    @app.after_request
    def log_response(response):
        logger = get_logger('mirofish.request')
        logger.debug(f"响应: {response.status_code}")
        return response
    
    # 注册蓝图
    from .api import graph_bp, simulation_bp, report_bp
    app.register_blueprint(graph_bp, url_prefix='/api/graph')
    app.register_blueprint(simulation_bp, url_prefix='/api/simulation')
    app.register_blueprint(report_bp, url_prefix='/api/report')
    
    # 健康检查
    @app.route('/health')
    def health():
        return {'status': 'ok', 'service': 'MiroFish Backend'}

    # SPA 前端静态资源服务（生产环境）
    # 在 /api/* 和 /health 之外的所有路径，返回前端构建产物。
    # 由于蓝图路由带有 /api/ 前缀，路由匹配优先级会高于下面的 catch-all。
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_spa(path):
        if not os.path.isdir(app.static_folder):
            return (
                {
                    'error': 'frontend not built',
                    'hint': 'run `npm --prefix frontend run build` or set FRONTEND_DIST_DIR',
                    'static_folder': app.static_folder,
                },
                503,
            )
        # 如果请求的是真实存在的静态文件，直接返回它
        candidate = os.path.join(app.static_folder, path)
        if path and os.path.isfile(candidate):
            return send_from_directory(app.static_folder, path)
        # 否则回退到 index.html（SPA 路由由前端处理）
        return send_from_directory(app.static_folder, 'index.html')

    if should_log_startup:
        logger.info("MiroFish Backend 启动完成")

    return app

