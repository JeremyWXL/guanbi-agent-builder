#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 按量付费（A2M / Machine Pay）收款服务 - Flask 实现

实现 402 协议核心流程：
1. 无 Payment-Proof：返回 HTTP 402 + Payment-Needed Header（Base64URL 账单）
2. 有 Payment-Proof：调用 alipay.aipay.agent.payment.verify 严格验付
3. 验付通过后原子生成资源，调用 alipay.aipay.agent.fulfillment.confirm 履约确认
4. 履约确认成功后才交付资源并标记订单完成

配置来源：项目根目录 .alipay-sandbox.json（沙箱），服务端加载器直接读取该文件；
私钥使用 appPrivatePkcsKey（PKCS#1，Python 适用），不做任何格式转换或 PEM 包装。
"""

import base64
import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from Crypto.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import pkcs1_15
from flask import Flask, Response, request

from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
from alipay.aop.api.DefaultAlipayClient import DefaultAlipayClient
from alipay.aop.api.request.AlipayAipayAgentPaymentVerifyRequest import (
    AlipayAipayAgentPaymentVerifyRequest,
)
from alipay.aop.api.request.AlipayAipayAgentFulfillmentConfirmRequest import (
    AlipayAipayAgentFulfillmentConfirmRequest,
)
from alipay.aop.api.domain.AlipayAipayAgentPaymentVerifyModel import (
    AlipayAipayAgentPaymentVerifyModel,
)
from alipay.aop.api.domain.AlipayAipayAgentFulfillmentConfirmModel import (
    AlipayAipayAgentFulfillmentConfirmModel,
)

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
SANDBOX_CONFIG_PATH = os.path.join(PROJECT_ROOT, '.alipay-sandbox.json')
ORDER_DB_PATH = os.path.join(PROJECT_ROOT, '.a2m-orders.db')

RESOURCE_CONFIG = {
    'path': '/a2m/resource',
    'goodsName': 'Data Agent 智能分析助手搭建服务',
}

app = Flask(__name__)


# ==================== 配置加载（生产环境变量优先，缺省回退本地沙箱配置） ====================

def load_alipay_config():
    """生产模式：AIPAY_APP_ID / AIPAY_PRIVATE_PKCS_KEY / AIPAY_ALIPAY_PUBLIC_KEY /
    ALIPAY_SELLER_ID 四个环境变量齐备时，直接使用生产配置（appId=2021 开头、
    网关默认为生产网关、serviceId 必须为 API_ 开头的真实值）。
    任一缺失时回退读取本地已验证的沙箱配置文件，保持沙箱调试可用。"""
    env_app_id = os.environ.get('AIPAY_APP_ID')
    env_private_key = os.environ.get('AIPAY_PRIVATE_PKCS_KEY')
    env_alipay_public_key = os.environ.get('AIPAY_ALIPAY_PUBLIC_KEY')
    env_seller_id = os.environ.get('ALIPAY_SELLER_ID')
    if env_app_id and env_private_key and env_alipay_public_key and env_seller_id:
        service_id = os.environ.get('ALIPAY_SERVICE_ID')
        if not service_id:
            raise RuntimeError(
                '生产模式缺少 ALIPAY_SERVICE_ID（API_ 开头的真实服务 ID）'
            )
        return {
            'appId': env_app_id,
            'privateKey': env_private_key,
            'alipayPublicKey': env_alipay_public_key,
            'sellerId': env_seller_id,
            'serviceId': service_id,
            'gateway': os.environ.get(
                'ALIPAY_GATEWAY', 'https://openapi.alipay.com/gateway.do'
            ),
        }
    with open(SANDBOX_CONFIG_PATH, 'r', encoding='utf-8') as f:
        sandbox = json.load(f)
    apps = sandbox.get('appIds') or []
    if not apps:
        raise RuntimeError('沙箱配置缺少 appIds')
    app_cfg = apps[0]
    return {
        'appId': app_cfg['appId'],
        'privateKey': app_cfg['appPrivatePkcsKey'],
        'alipayPublicKey': app_cfg['alipayPublicKey'],
        'sellerId': app_cfg['pid'],
        # 沙箱固定 api_mock_service_id；上线前替换为服务市场真实 serviceId
        'serviceId': os.environ.get('ALIPAY_SERVICE_ID', 'api_mock_service_id'),
        # 默认沙箱网关；生产部署时显式设置 ALIPAY_GATEWAY=https://openapi.alipay.com/gateway.do
        'gateway': os.environ.get(
            'ALIPAY_GATEWAY', 'https://openapi-sandbox.dl.alipaydev.com/gateway.do'
        ),
    }


ALIPAY_CONFIG = load_alipay_config()


def execute_with_retry(client, request, attempts=3, delay=1.0):
    """SDK 网关调用带有限重试，容忍网关/网络瞬时非 200。"""
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return client.execute(request)
        except Exception as e:
            last_error = e
            print(f'SDK 调用第 {attempt}/{attempts} 次失败：{e}')
            if attempt < attempts:
                time.sleep(delay)
    raise last_error


def init_alipay_client():
    config = AlipayClientConfig()
    config.server_url = ALIPAY_CONFIG['gateway']
    config.app_id = ALIPAY_CONFIG['appId']
    config.app_private_key = ALIPAY_CONFIG['privateKey']
    config.alipay_public_key = ALIPAY_CONFIG['alipayPublicKey']
    config.charset = 'utf-8'
    config.sign_type = 'RSA2'
    return DefaultAlipayClient(alipay_client_config=config)


# ==================== 订单持久化（SQLite，唯一约束 + 事务保证幂等） ====================

class SqliteOrderRepository:
    """真实持久化订单仓：create_pending / find_by_out_trade_no /
    prepare_fulfillment（原子履约准备，资源只生成一次）/ mark_fulfilled。"""

    def __init__(self, db_path):
        self.db_path = db_path
        self._init_schema()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS a2m_orders (
                    out_trade_no TEXT PRIMARY KEY,
                    amount TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    goods_name TEXT NOT NULL,
                    pay_before TEXT NOT NULL,
                    order_status TEXT NOT NULL,
                    fulfill_status TEXT NOT NULL,
                    trade_no TEXT,
                    service_result TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _row_to_order(row):
        if row is None:
            return None
        return dict(row)

    def create_pending(self, order):
        now = datetime.now(timezone.utc).astimezone().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO a2m_orders (
                    out_trade_no, amount, currency, resource_id, goods_name,
                    pay_before, order_status, fulfill_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order['out_trade_no'], order['amount'], order['currency'],
                    order['resource_id'], order['goods_name'], order['pay_before'],
                    order['order_status'], order['fulfill_status'], now, now,
                ),
            )

    def find_by_out_trade_no(self, out_trade_no):
        with self._connect() as conn:
            row = conn.execute(
                'SELECT * FROM a2m_orders WHERE out_trade_no = ?', (out_trade_no,)
            ).fetchone()
        return self._row_to_order(row)

    def prepare_fulfillment(self, request):
        """原子地校验订单并只生成一次资源。

        在同一事务内重读订单：已 FULFILLED / PENDING_CONFIRM 直接返回已持久化结果；
        否则生成资源并置为 PENDING_CONFIRM。返回 {state, service_result}。
        """
        conn = self._connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute(
                'SELECT * FROM a2m_orders WHERE out_trade_no = ?',
                (request['out_trade_no'],),
            ).fetchone()
            order = self._row_to_order(row)
            if order is None:
                conn.rollback()
                return None
            if (
                order['amount'] != request['expected_amount']
                or order['resource_id'] != request['expected_resource_id']
            ):
                conn.rollback()
                return None
            if order['fulfill_status'] in ('PENDING_CONFIRM', 'FULFILLED'):
                result = {
                    'state': order['fulfill_status'],
                    'service_result': order['service_result'],
                }
                conn.commit()
                return result
            service_result = request['create_resource']()
            now = datetime.now(timezone.utc).astimezone().isoformat()
            cursor = conn.execute(
                """
                UPDATE a2m_orders
                SET fulfill_status = 'PENDING_CONFIRM', service_result = ?,
                    trade_no = ?, order_status = 'PAID', updated_at = ?
                WHERE out_trade_no = ? AND fulfill_status = 'UNFULFILLED'
                """,
                (service_result, request['trade_no'], now, request['out_trade_no']),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return None
            conn.commit()
            return {'state': 'PENDING_CONFIRM', 'service_result': service_result}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mark_fulfilled(self, out_trade_no, trade_no):
        now = datetime.now(timezone.utc).astimezone().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE a2m_orders
                SET fulfill_status = 'FULFILLED', trade_no = ?, updated_at = ?
                WHERE out_trade_no = ?
                """,
                (trade_no, now, out_trade_no),
            )


ORDER_REPOSITORY = SqliteOrderRepository(ORDER_DB_PATH)


# ==================== 工具方法 ====================

def format_alipay_timestamp(dt=None):
    if dt is None:
        dt = datetime.now()
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def generate_seller_signature(params, private_key):
    """生成商家签名：按 key 字典序拼接后 RSA2 签名。原始私钥只临时解码为
    密钥对象供原生密码库调用，不写回配置、不做格式转换。"""
    sorted_keys = sorted(params.keys())
    sign_content = []
    for key in sorted_keys:
        value = params[key]
        if value is not None and value != '':
            sign_content.append(f'{key}={value}')
    sign_string = '&'.join(sign_content)

    key_der = base64.b64decode(private_key, validate=True)
    key = RSA.import_key(key_der)
    digest = SHA256.new(sign_string.encode('utf-8'))
    signature = pkcs1_15.new(key).sign(digest)
    return base64.b64encode(signature).decode('utf-8')


def base64url_encode(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('utf-8')


def base64url_decode(data):
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data).decode('utf-8')


def normalize_amount(value):
    text = str(value or '').strip()
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?', text):
        return None
    return f'{Decimal(text):.2f}'


def amounts_equal(left, right):
    left_amount = normalize_amount(left)
    right_amount = normalize_amount(right)
    return (
        left_amount is not None
        and right_amount is not None
        and left_amount == right_amount
    )


def is_future(value):
    try:
        return datetime.fromisoformat(value).timestamp() > time.time()
    except (TypeError, ValueError):
        return False


def is_exact_sandbox_mode():
    return (
        ALIPAY_CONFIG['gateway'] == 'https://openapi-sandbox.dl.alipaydev.com/gateway.do'
        and ALIPAY_CONFIG['serviceId'] == 'api_mock_service_id'
    )


def json_response(data, status_code=200, headers=None):
    response = Response(
        json.dumps(data, ensure_ascii=False),
        status=status_code,
        mimetype='application/json; charset=utf-8',
    )
    if headers:
        for key, value in headers.items():
            response.headers[key] = value
    return response


# ==================== A2M 资源接口 ====================

@app.route(RESOURCE_CONFIG['path'], methods=['GET'])
def handle_resource():
    payment_proof = request.headers.get('Payment-Proof')
    if not payment_proof or not payment_proof.strip():
        return create_payment_required_response()
    return verify_payment_and_deliver_resource(payment_proof)


def create_payment_required_response():
    """创建 402 支付请求响应（先持久化订单，再返回 Payment-Needed Header）。"""
    try:
        out_trade_no = f"ORDER_{int(time.time() * 1000)}_{uuid.uuid4().hex[:12]}"
        # 单价默认 0.1 元/次（与服务市场登记一致）；沙箱调试可设 ALIPAY_PRICE=0.01
        amount = os.environ.get('ALIPAY_PRICE', '0.1')
        currency = 'CNY'
        resource_id = RESOURCE_CONFIG['path']
        goods_name = RESOURCE_CONFIG['goodsName']
        pay_before = (
            datetime.now(timezone.utc).astimezone() + timedelta(minutes=30)
        ).isoformat()

        seller_signature = generate_seller_signature(
            {
                'amount': amount,
                'currency': currency,
                'goods_name': goods_name,
                'out_trade_no': out_trade_no,
                'pay_before': pay_before,
                'resource_id': resource_id,
                'seller_id': ALIPAY_CONFIG['sellerId'],
                'service_id': ALIPAY_CONFIG['serviceId'],
            },
            ALIPAY_CONFIG['privateKey'],
        )

        ORDER_REPOSITORY.create_pending({
            'out_trade_no': out_trade_no,
            'amount': normalize_amount(amount),
            'currency': currency,
            'resource_id': resource_id,
            'goods_name': goods_name,
            'pay_before': pay_before,
            'order_status': 'PENDING_PAYMENT',
            'fulfill_status': 'UNFULFILLED',
        })

        payment_needed = {
            'protocol': {
                'out_trade_no': out_trade_no,
                'amount': amount,
                'currency': currency,
                'resource_id': resource_id,
                'pay_before': pay_before,
                'seller_signature': seller_signature,
                'seller_sign_type': 'RSA2',
                'seller_unique_id': ALIPAY_CONFIG['sellerId'],
            },
            'method': {
                'seller_name': goods_name,
                'seller_id': ALIPAY_CONFIG['sellerId'],
                'seller_app_id': ALIPAY_CONFIG['appId'],
                'goods_name': goods_name,
                'seller_unique_id_key': 'seller_id',
                'service_id': ALIPAY_CONFIG['serviceId'],
            },
        }

        payment_needed_encoded = base64url_encode(
            json.dumps(payment_needed, ensure_ascii=False)
        )
        response_data = {
            'code': 'Payment-Needed',
            'message': '需要支付',
            'out_trade_no': out_trade_no,
            'amount': amount,
            'currency': currency,
            'goods_name': goods_name,
        }
        print(f'创建支付订单成功：outTradeNo={out_trade_no}, amount={amount}')
        return json_response(
            response_data,
            status_code=402,
            headers={'Payment-Needed': payment_needed_encoded},
        )
    except Exception as e:
        print(f'创建订单失败：{e}')
        return json_response(
            {'code': 'CREATE_ORDER_ERROR', 'message': f'创建订单失败：{e}'},
            status_code=500,
        )


def verify_payment_and_deliver_resource(payment_proof):
    """验付 Payment-Proof，通过后原子履约并交付资源。"""
    try:
        # 1. 解析 Payment-Proof
        try:
            decoded_proof = base64url_decode(payment_proof)
            proof_json = json.loads(decoded_proof)
            protocol = proof_json.get('protocol', {})
            payment_proof_value = protocol.get('payment_proof')
            trade_no = protocol.get('trade_no')
            method = proof_json.get('method', {})
            client_session = method.get('client_session')
            if not payment_proof_value or not payment_proof_value.strip():
                return create_payment_required_response()
            if not trade_no or not trade_no.strip():
                return create_payment_required_response()
        except Exception as e:
            print(f'Payment-Proof 解析失败：{e}')
            return create_payment_required_response()

        # 2. 调用 alipay.aipay.agent.payment.verify（必须使用 Model 类）
        alipay_client = init_alipay_client()
        verify_request = AlipayAipayAgentPaymentVerifyRequest()
        model = AlipayAipayAgentPaymentVerifyModel()
        model.payment_proof = payment_proof_value
        model.trade_no = trade_no
        if client_session:
            model.client_session = client_session
        verify_request.biz_model = model

        verify_response = json.loads(execute_with_retry(alipay_client, verify_request))
        response_data = verify_response.get(
            'alipay_aipay_agent_payment_verify_response', verify_response
        )
        if response_data.get('code') != '10000':
            print(f'支付凭证验证失败：{response_data.get("sub_msg")}')
            return create_payment_required_response()

        # 3. 严格校验验付结果
        returned_trade_no = (
            response_data.get('trade_no') or response_data.get('tradeNo') or ''
        )
        verify_out_trade_no = (
            response_data.get('out_trade_no') or response_data.get('outTradeNo') or ''
        )
        returned_amount = response_data.get('amount')
        returned_resource_id = (
            response_data.get('resource_id') or response_data.get('resourceId') or ''
        )
        active = response_data.get('active')

        order = (
            ORDER_REPOSITORY.find_by_out_trade_no(verify_out_trade_no)
            if verify_out_trade_no
            else None
        )
        sandbox_mode = is_exact_sandbox_mode()
        verify_trade_no = returned_trade_no or (trade_no if sandbox_mode else '')
        verify_amount = returned_amount or (
            order.get('amount') if sandbox_mode and order else ''
        )
        resource_id_verified = returned_resource_id or (
            order.get('resource_id') if sandbox_mode and order else ''
        )

        print(
            f'支付凭证验证成功：tradeNo={verify_trade_no}, '
            f'outTradeNo={verify_out_trade_no}'
        )

        if (
            active is not True
            or not verify_trade_no
            or verify_trade_no != trade_no
            or not verify_out_trade_no
            or not resource_id_verified
        ):
            print(f'支付凭证无效或已过期：outTradeNo={verify_out_trade_no}')
            return create_payment_required_response()

        amount_matches = order and amounts_equal(order.get('amount'), verify_amount)
        resource_matches = (
            order
            and order.get('resource_id') == resource_id_verified
            and resource_id_verified == RESOURCE_CONFIG['path']
        )
        fulfill_status = order.get('fulfill_status') if order else None
        fulfillment_in_progress = fulfill_status in ('PENDING_CONFIRM', 'FULFILLED')
        order_usable = (
            order
            and order.get('currency') == 'CNY'
            and order.get('order_status') in ('PENDING_PAYMENT', 'PAID')
            and fulfill_status in ('UNFULFILLED', 'PENDING_CONFIRM', 'FULFILLED')
            and (fulfillment_in_progress or is_future(order.get('pay_before')))
        )
        if not amount_matches or not resource_matches or not order_usable:
            return create_payment_required_response()

        # 4. 原子履约准备：资源只生成一次
        fulfillment = ORDER_REPOSITORY.prepare_fulfillment({
            'out_trade_no': verify_out_trade_no,
            'trade_no': verify_trade_no,
            'expected_amount': normalize_amount(verify_amount),
            'expected_resource_id': resource_id_verified,
            'create_resource': lambda: generate_service_resource(resource_id_verified),
        })
        if (
            not fulfillment
            or fulfillment.get('state') not in ('PENDING_CONFIRM', 'FULFILLED')
            or not fulfillment.get('service_result')
        ):
            raise RuntimeError('prepare_fulfillment 未返回已持久化的履约结果')
        service_result = fulfillment['service_result']
        if fulfillment['state'] == 'FULFILLED':
            return successful_resource_response(
                verify_trade_no, verify_out_trade_no,
                resource_id_verified, service_result, True,
            )

        print(
            f'资源已生成，准备发送履约确认：outTradeNo={verify_out_trade_no}, '
            f'tradeNo={verify_trade_no}'
        )

        # 5. 履约确认成功后才最终交付；失败允许同一 Payment-Proof 重试
        if not send_fulfillment_confirm(verify_trade_no):
            return json_response(
                {
                    'code': 'FULFILLMENT_CONFIRM_FAILED',
                    'message': '资源已生成但履约确认失败，请稍后使用同一 Payment-Proof 重试',
                },
                status_code=502,
            )

        ORDER_REPOSITORY.mark_fulfilled(verify_out_trade_no, verify_trade_no)
        print(
            f'履约确认成功：outTradeNo={verify_out_trade_no}, '
            f'tradeNo={verify_trade_no}'
        )
        return successful_resource_response(
            verify_trade_no, verify_out_trade_no,
            resource_id_verified, service_result, False,
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f'支付凭证验证异常：{e}')
        return json_response(
            {'code': 'VERIFY_FAILED', 'message': f'支付凭证验证失败：{e}'},
            status_code=500,
        )


def successful_resource_response(
    trade_no, out_trade_no, resource_id, service_result, already_fulfilled
):
    payment_validation = base64url_encode(json.dumps({
        'trade_no': trade_no,
        'out_trade_no': out_trade_no,
        'validated': True,
        'resource_id': resource_id,
    }, ensure_ascii=False))
    return json_response(
        {
            'resource_id': resource_id,
            'content': service_result,
            'trade_no': trade_no,
            'out_trade_no': out_trade_no,
            'already_fulfilled': already_fulfilled,
            'fulfillment_confirmed': True,
        },
        headers={'Payment-Validation': payment_validation},
    )


def generate_service_resource(resource_id):
    return json.dumps({
        'status': 'success',
        'service_type': 'GUANBI_AGENT_BUILDER',
        'resource_id': resource_id,
        'content': '观远 BI 经营分析助手搭建服务资源（按量付费履约内容）',
        'generated_at': datetime.now(timezone.utc).astimezone().isoformat(),
    }, ensure_ascii=False)


def send_fulfillment_confirm(trade_no):
    """调用 alipay.aipay.agent.fulfillment.confirm 发送履约确认。"""
    if not trade_no:
        print('履约确认失败：tradeNo 为空')
        return False
    try:
        print(f'开始发送履约确认：tradeNo={trade_no}')
        alipay_client = init_alipay_client()
        confirm_request = AlipayAipayAgentFulfillmentConfirmRequest()
        model = AlipayAipayAgentFulfillmentConfirmModel()
        model.trade_no = trade_no
        confirm_request.biz_model = model

        response = json.loads(execute_with_retry(alipay_client, confirm_request))
        response_data = response.get(
            'alipay_aipay_agent_fulfillment_confirm_response', response
        )
        if response_data.get('code') == '10000':
            print(f'履约确认成功：tradeNo={trade_no}')
            return True
        print(
            f'履约确认失败：tradeNo={trade_no}, '
            f'errorCode={response_data.get("sub_code")}, '
            f'errorMsg={response_data.get("sub_msg")}'
        )
        return False
    except Exception as e:
        print(f'履约确认异常：tradeNo={trade_no}, error={e}')
        return False


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5000'))
    print(f"A2M 按量付费服务已启动：http://localhost:{port}{RESOURCE_CONFIG['path']}")
    app.run(host='127.0.0.1', port=port, debug=False)
