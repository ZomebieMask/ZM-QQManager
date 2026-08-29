"""
ZM-QQManager - 功能强大的 QQ 群管理插件
作者: ZM
"""
import re
import time
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, register
from astrbot.api.star.star_handler import star_receiver
from astrbot.api import logger


@register("ZM-QQManager", "ZM", "1.0.0")
class ZMQQManager:
    """ZM-QQManager 群管理插件"""

    def __init__(self, context: Context):
        self.context = context
        self.db = context.kv_db  # KV 数据库
        self.message_history: Dict[str, List[Dict]] = {}  # 消息历史记录
        self.max_history_per_group = 100  # 每个群最多保存的消息数

        # 广告检测关键词配置
        self.ad_keywords = {
            # 广告短语 (权重: 3)
            'phrases': [
                '加微信', '加QQ', '加群', '进群', '私聊', '联系方式',
                '代理', '招代理', '诚招', '兼职', '赚钱', '日入',
                '月入', '收益', '盈利', '稳赚', '零投资', '高回报',
                '包教包会', '一对一', '免费领', '限时优惠', '打折',
                '低价', '便宜', '清仓', '促销', '秒杀'
            ],
            # 联系方式模式 (权重: 4)
            'contact_patterns': [
                r'[vVwW][xX][:：]?\s*[a-zA-Z0-9_-]{5,}',  # vx: xxxxx
                r'[qQ]{1,2}[:：]?\s*[0-9]{5,}',  # qq: 12345
                r'微信[:：]?\s*[a-zA-Z0-9_-]{5,}',
            ],
            # 手机号 (权重: 3)
            'phone_pattern': r'1[3-9]\d{9}',
            # 外链 (权重: 2)
            'url_pattern': r'https?://[^\s]+',
            # 促销词汇 (权重: 2)
            'promo_words': ['优惠', '折扣', '特价', '限时', '抢购', '包邮']
        }

        logger.info("ZM-QQManager 插件已加载")

    def _parse_time_duration(self, time_str: str) -> Optional[int]:
        """
        解析时间字符串，返回秒数
        支持格式: 数字 + d/w/m/y (天/周/月/年)
        """
        if not time_str:
            return None

        match = re.match(r'(\d+)([dwmy])', time_str.lower())
        if not match:
            return None

        value, unit = int(match.group(1)), match.group(2)

        if unit == 'd':
            return value * 86400  # 天
        elif unit == 'w':
            return value * 604800  # 周
        elif unit == 'm':
            return value * 2592000  # 月 (30天)
        elif unit == 'y':
            return value * 31536000  # 年 (365天)

        return None

    def _replace_placeholders(self, text: str, event: AstrMessageEvent) -> str:
        """替换文本中的占位符"""
        replacements = {
            '{at}': f"[CQ:at,qq={event.message_obj.sender.user_id}]",
            '{name}': event.message_obj.sender.nickname or str(event.message_obj.sender.user_id),
            '{user_id}': str(event.message_obj.sender.user_id),
            '{group_id}': str(event.message_obj.group_id) if event.message_obj.group_id else 'N/A'
        }

        for placeholder, value in replacements.items():
            text = text.replace(placeholder, value)

        return text

    def _get_ban_list_key(self, group_id: str) -> str:
        """获取封禁列表的键名"""
        return f"zm_qqmanager_banlist_{group_id}"

    def _get_ad_key(self, group_id: str) -> str:
        """获取广告配置的键名"""
        return f"zm_qqmanager_ad_{group_id}"

    def _get_welcome_key(self, group_id: str) -> str:
        """获取欢迎消息的键名"""
        return f"zm_qqmanager_welcome_{group_id}"

    def _get_adban_key(self, group_id: str) -> str:
        """获取广告拦截开关的键名"""
        return f"zm_qqmanager_adban_{group_id}"

    def _is_user_banned(self, group_id: str, user_id: str) -> bool:
        """检查用户是否在封禁列表中"""
        key = self._get_ban_list_key(group_id)
        ban_list = self.db.get(key, [])
        return user_id in ban_list

    def _add_to_ban_list(self, group_id: str, user_id: str):
        """添加用户到封禁列表"""
        key = self._get_ban_list_key(group_id)
        ban_list = self.db.get(key, [])
        if user_id not in ban_list:
            ban_list.append(user_id)
            self.db.put(key, ban_list)

    def _remove_from_ban_list(self, group_id: str, user_id: str):
        """从封禁列表移除用户"""
        key = self._get_ban_list_key(group_id)
        ban_list = self.db.get(key, [])
        if user_id in ban_list:
            ban_list.remove(user_id)
            self.db.put(key, ban_list)

    def _extract_user_id(self, target: str) -> Optional[str]:
        """从文本中提取用户 ID (支持 @、CQ码、纯数字)"""
        # CQ:at,qq=123456
        cq_match = re.search(r'\[CQ:at,qq=(\d+)\]', target)
        if cq_match:
            return cq_match.group(1)

        # 纯数字
        number_match = re.search(r'\d{5,}', target)
        if number_match:
            return number_match.group(0)

        return None

    def _record_message(self, event: AstrMessageEvent):
        """记录消息到历史"""
        if not event.message_obj.group_id:
            return

        group_id = str(event.message_obj.group_id)
        if group_id not in self.message_history:
            self.message_history[group_id] = []

        # 添加消息记录
        self.message_history[group_id].append({
            'message_id': event.message_obj.message_id,
            'user_id': event.message_obj.sender.user_id,
            'timestamp': time.time(),
            'content': event.message_str
        })

        # 限制历史记录数量
        if len(self.message_history[group_id]) > self.max_history_per_group:
            self.message_history[group_id] = self.message_history[group_id][-self.max_history_per_group:]

    def _calculate_ad_score(self, text: str) -> int:
        """计算广告评分，返回总分"""
        score = 0

        # 检查广告短语 (权重: 3)
        for phrase in self.ad_keywords['phrases']:
            if phrase in text:
                score += 3

        # 检查联系方式模式 (权重: 4)
        for pattern in self.ad_keywords['contact_patterns']:
            if re.search(pattern, text):
                score += 4

        # 检查手机号 (权重: 3)
        if re.search(self.ad_keywords['phone_pattern'], text):
            score += 3

        # 检查外链 (权重: 2)
        if re.search(self.ad_keywords['url_pattern'], text):
            score += 2

        # 检查促销词汇 (权重: 2)
        for word in self.ad_keywords['promo_words']:
            if word in text:
                score += 2

        return score

    async def _mute_user(self, event: AstrMessageEvent, user_id: str, duration: int) -> str:
        """禁言用户"""
        try:
            # 调用 OneBot API 禁言
            await event.context.adapter.call_api(
                "set_group_ban",
                group_id=event.message_obj.group_id,
                user_id=int(user_id),
                duration=duration
            )
            return f"已禁言用户 {user_id}，时长: {duration} 秒"
        except Exception as e:
            logger.error(f"禁言失败: {e}")
            return f"禁言失败: {str(e)}"

    async def _kick_user(self, event: AstrMessageEvent, user_id: str) -> str:
        """踢出用户"""
        try:
            await event.context.adapter.call_api(
                "set_group_kick",
                group_id=event.message_obj.group_id,
                user_id=int(user_id),
                reject_add_request=False
            )
            return f"已踢出用户 {user_id}"
        except Exception as e:
            logger.error(f"踢出失败: {e}")
            return f"踢出失败: {str(e)}"

    async def _recall_message(self, event: AstrMessageEvent, message_id: int) -> bool:
        """撤回消息"""
        try:
            await event.context.adapter.call_api(
                "delete_msg",
                message_id=message_id
            )
            return True
        except Exception as e:
            logger.error(f"撤回消息失败: {e}")
            return False

    async def _set_admin(self, event: AstrMessageEvent, user_id: str, enable: bool) -> str:
        """设置管理员"""
        try:
            await event.context.adapter.call_api(
                "set_group_admin",
                group_id=event.message_obj.group_id,
                user_id=int(user_id),
                enable=enable
            )
            action = "设置" if enable else "取消"
            return f"已{action}用户 {user_id} 的管理员权限"
        except Exception as e:
            logger.error(f"设置管理员失败: {e}")
            return f"设置管理员失败: {str(e)}"

    async def _set_title(self, event: AstrMessageEvent, user_id: str, title: str) -> str:
        """设置群头衔"""
        try:
            await event.context.adapter.call_api(
                "set_group_special_title",
                group_id=event.message_obj.group_id,
                user_id=int(user_id),
                special_title=title,
                duration=-1  # 永久
            )
            return f"已设置用户 {user_id} 的群头衔为: {title}"
        except Exception as e:
            logger.error(f"设置头衔失败: {e}")
            return f"设置头衔失败: {str(e)}"

    async def _get_group_member_list(self, event: AstrMessageEvent) -> List[Dict]:
        """获取群成员列表"""
        try:
            result = await event.context.adapter.call_api(
                "get_group_member_list",
                group_id=event.message_obj.group_id
            )
            return result
        except Exception as e:
            logger.error(f"获取群成员列表失败: {e}")
            return []

    @star_receiver(command="mute")
    async def handle_mute(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理禁言命令: /mute <成员> [时间]"""
        if not event.message_obj.group_id:
            return MessageEventResult().message("此命令仅在群聊中可用")

        parts = event.message_str.split(maxsplit=2)
        if len(parts) < 2:
            return MessageEventResult().message("用法: /mute <成员> [时间]\n时间格式: 数字+d/w/m/y (例: 30d, 1w)")

        target = parts[1]
        duration_str = parts[2] if len(parts) > 2 else "10m"

        user_id = self._extract_user_id(target)
        if not user_id:
            return MessageEventResult().message("无法识别目标用户，请 @用户 或提供 QQ 号")

        duration = self._parse_time_duration(duration_str)
        if duration is None:
            return MessageEventResult().message("时间格式错误，请使用: 数字+d/w/m/y (例: 30d)")

        result = await self._mute_user(event, user_id, duration)
        return MessageEventResult().message(result)

    @star_receiver(command="kick")
    async def handle_kick(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理踢人命令: /kick <成员> 或 /kick <时间>"""
        if not event.message_obj.group_id:
            return MessageEventResult().message("此命令仅在群聊中可用")

        parts = event.message_str.split(maxsplit=1)
        if len(parts) < 2:
            return MessageEventResult().message("用法: /kick <成员> 或 /kick <时间> (清理不活跃)")

        target = parts[1].strip()

        # 检查是否是时间格式 (清理不活跃成员)
        duration = self._parse_time_duration(target)
        if duration:
            # 清理不活跃成员
            members = await self._get_group_member_list(event)
            if not members:
                return MessageEventResult().message("无法获取群成员列表")

            current_time = int(time.time())
            kicked_count = 0
            inactive_threshold = current_time - duration

            for member in members:
                last_sent_time = member.get('last_sent_time', 0)
                if last_sent_time < inactive_threshold:
                    user_id = str(member['user_id'])
                    await self._kick_user(event, user_id)
                    kicked_count += 1
                    await asyncio.sleep(0.5)  # 避免频繁操作

            return MessageEventResult().message(f"已踢出 {kicked_count} 个不活跃成员")

        # 踢出指定成员
        user_id = self._extract_user_id(target)
        if not user_id:
            return MessageEventResult().message("无法识别目标用户，请 @用户、提供 QQ 号或时间格式")

        result = await self._kick_user(event, user_id)
        return MessageEventResult().message(result)

    @star_receiver(command="ban")
    async def handle_ban(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理封禁命令: /ban <成员>"""
        if not event.message_obj.group_id:
            return MessageEventResult().message("此命令仅在群聊中可用")

        parts = event.message_str.split(maxsplit=1)
        if len(parts) < 2:
            return MessageEventResult().message("用法: /ban <成员>")

        user_id = self._extract_user_id(parts[1])
        if not user_id:
            return MessageEventResult().message("无法识别目标用户")

        # 添加到封禁列表
        self._add_to_ban_list(str(event.message_obj.group_id), user_id)

        # 踢出用户
        result = await self._kick_user(event, user_id)
        return MessageEventResult().message(f"{result}\n已加入封禁列表")

    @star_receiver(command="unban")
    async def handle_unban(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理解封命令: /unban <QQ号>"""
        if not event.message_obj.group_id:
            return MessageEventResult().message("此命令仅在群聊中可用")

        parts = event.message_str.split(maxsplit=1)
        if len(parts) < 2:
            return MessageEventResult().message("用法: /unban <QQ号>")

        user_id = self._extract_user_id(parts[1])
        if not user_id:
            return MessageEventResult().message("无法识别 QQ 号")

        self._remove_from_ban_list(str(event.message_obj.group_id), user_id)
        return MessageEventResult().message(f"已将 {user_id} 从封禁列表移除")

    @star_receiver(command="recall")
    async def handle_recall(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理撤回命令: /recall 或 /recall <数量>"""
        if not event.message_obj.group_id:
            return MessageEventResult().message("此命令仅在群聊中可用")

        group_id = str(event.message_obj.group_id)
        parts = event.message_str.split(maxsplit=1)

        # 如果回复了消息，撤回被回复的消息
        if hasattr(event.message_obj, 'reply') and event.message_obj.reply:
            reply_msg_id = event.message_obj.reply.message_id
            success = await self._recall_message(event, reply_msg_id)
            return MessageEventResult().message("已撤回被回复的消息" if success else "撤回失败")

        # 撤回最近的 N 条消息
        count = 1
        if len(parts) > 1:
            try:
                count = int(parts[1])
            except ValueError:
                return MessageEventResult().message("数量必须是数字")

        if group_id not in self.message_history:
            return MessageEventResult().message("暂无消息记录")

        messages = self.message_history[group_id][-count:]
        recalled = 0

        for msg in reversed(messages):
            if await self._recall_message(event, msg['message_id']):
                recalled += 1

        return MessageEventResult().message(f"已撤回 {recalled}/{count} 条消息")

    @star_receiver(command="ad")
    async def handle_ad(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理广告命令: /ad, /ad set <文本>, /ad clear, /ad reset"""
        if not event.message_obj.group_id:
            return MessageEventResult().message("此命令仅在群聊中可用")

        group_id = str(event.message_obj.group_id)
        key = self._get_ad_key(group_id)
        parts = event.message_str.split(maxsplit=2)

        if len(parts) == 1:
            # 发布广告
            ad_data = self.db.get(key)
            if not ad_data:
                return MessageEventResult().message("本群尚未设置广告")
            return MessageEventResult().message(ad_data.get('content', ''))

        subcommand = parts[1].lower()

        if subcommand == "set":
            # 保存广告
            if len(parts) < 3:
                return MessageEventResult().message("用法: /ad set <文本>")
            content = parts[2]
            self.db.put(key, {'content': content, 'updated_at': time.time()})
            return MessageEventResult().message("广告已保存")

        elif subcommand == "clear":
            # 清空广告
            self.db.delete(key)
            return MessageEventResult().message("广告已清空")

        elif subcommand == "reset":
            # 恢复默认广告
            default_ad = "这是一条默认广告，请使用 /ad set 设置自定义广告"
            self.db.put(key, {'content': default_ad, 'updated_at': time.time()})
            return MessageEventResult().message("已恢复默认广告")

        return MessageEventResult().message("未知子命令，可用: set, clear, reset")

    @star_receiver(command="adban")
    async def handle_adban(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理广告拦截命令: /adban, /adban on, /adban off"""
        if not event.message_obj.group_id:
            return MessageEventResult().message("此命令仅在群聊中可用")

        group_id = str(event.message_obj.group_id)
        key = self._get_adban_key(group_id)
        parts = event.message_str.split()

        current_state = self.db.get(key, False)

        if len(parts) == 1:
            # 切换状态
            new_state = not current_state
            self.db.put(key, new_state)
            return MessageEventResult().message(f"广告拦截已{'开启' if new_state else '关闭'}")

        subcommand = parts[1].lower()
        if subcommand == "on":
            self.db.put(key, True)
            return MessageEventResult().message("广告拦截已开启")
        elif subcommand == "off":
            self.db.put(key, False)
            return MessageEventResult().message("广告拦截已关闭")

        return MessageEventResult().message("用法: /adban, /adban on, /adban off")

    @star_receiver(command="wel")
    async def handle_welcome(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理欢迎消息命令"""
        if not event.message_obj.group_id:
            return MessageEventResult().message("此命令仅在群聊中可用")

        group_id = str(event.message_obj.group_id)
        key = self._get_welcome_key(group_id)
        parts = event.message_str.split(maxsplit=2)

        if len(parts) == 1:
            # 手动执行欢迎
            welcome_data = self.db.get(key)
            if not welcome_data or not welcome_data.get('enabled'):
                return MessageEventResult().message("欢迎消息未启用")
            content = self._replace_placeholders(welcome_data.get('content', ''), event)
            return MessageEventResult().message(content)

        subcommand = parts[1].lower()

        if subcommand == "set":
            if len(parts) < 3:
                return MessageEventResult().message("用法: /wel set <文本>")
            content = parts[2]
            self.db.put(key, {'content': content, 'enabled': True})
            return MessageEventResult().message("欢迎消息已保存并启用")

        elif subcommand == "on":
            welcome_data = self.db.get(key, {})
            welcome_data['enabled'] = True
            self.db.put(key, welcome_data)
            return MessageEventResult().message("欢迎消息已启用")

        elif subcommand == "off":
            welcome_data = self.db.get(key, {})
            welcome_data['enabled'] = False
            self.db.put(key, welcome_data)
            return MessageEventResult().message("欢迎消息已关闭")

        elif subcommand == "reset":
            default_welcome = "欢迎 {at} 加入本群！"
            self.db.put(key, {'content': default_welcome, 'enabled': True})
            return MessageEventResult().message("已恢复默认欢迎消息")

        elif subcommand == "status":
            welcome_data = self.db.get(key)
            if not welcome_data:
                return MessageEventResult().message("欢迎消息未配置")
            enabled = welcome_data.get('enabled', False)
            content = welcome_data.get('content', '')
            return MessageEventResult().message(
                f"状态: {'已启用' if enabled else '已关闭'}\n"
                f"内容: {content}"
            )

        return MessageEventResult().message("可用子命令: set, on, off, reset, status")

    @star_receiver(command="title")
    async def handle_title(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理群头衔命令: /title @成员 文本 或 /title unset @成员"""
        if not event.message_obj.group_id:
            return MessageEventResult().message("此命令仅在群聊中可用")

        parts = event.message_str.split(maxsplit=2)
        if len(parts) < 2:
            return MessageEventResult().message("用法: /title @成员 <文本> 或 /title unset @成员")

        if parts[1].lower() == "unset":
            if len(parts) < 3:
                return MessageEventResult().message("用法: /title unset @成员")
            user_id = self._extract_user_id(parts[2])
            if not user_id:
                return MessageEventResult().message("无法识别目标用户")
            result = await self._set_title(event, user_id, "")
            return MessageEventResult().message(result)

        if len(parts) < 3:
            return MessageEventResult().message("用法: /title @成员 <文本>")

        user_id = self._extract_user_id(parts[1])
        if not user_id:
            return MessageEventResult().message("无法识别目标用户")

        title = self._replace_placeholders(parts[2], event)
        result = await self._set_title(event, user_id, title)
        return MessageEventResult().message(result)

    @star_receiver(command="op")
    async def handle_op(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理设置管理员命令: /op <成员>"""
        if not event.message_obj.group_id:
            return MessageEventResult().message("此命令仅在群聊中可用")

        parts = event.message_str.split(maxsplit=1)
        if len(parts) < 2:
            return MessageEventResult().message("用法: /op <成员>")

        user_id = self._extract_user_id(parts[1])
        if not user_id:
            return MessageEventResult().message("无法识别目标用户")

        result = await self._set_admin(event, user_id, True)
        return MessageEventResult().message(result)

    @star_receiver(command="deop")
    async def handle_deop(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理取消管理员命令: /deop <成员>"""
        if not event.message_obj.group_id:
            return MessageEventResult().message("此命令仅在群聊中可用")

        parts = event.message_str.split(maxsplit=1)
        if len(parts) < 2:
            return MessageEventResult().message("用法: /deop <成员>")

        user_id = self._extract_user_id(parts[1])
        if not user_id:
            return MessageEventResult().message("无法识别目标用户")

        result = await self._set_admin(event, user_id, False)
        return MessageEventResult().message(result)

    @star_receiver(command="slimefinder")
    async def handle_slimefinder(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理史莱姆区块查找命令: /slimefinder <version> <seed>"""
        parts = event.message_str.split(maxsplit=2)
        if len(parts) < 3:
            return MessageEventResult().message(
                "用法: /slimefinder <version> <seed>\n"
                "示例: /slimefinder 1.20.1 12345678"
            )

        version = parts[1]
        try:
            seed = int(parts[2])
        except ValueError:
            return MessageEventResult().message("种子必须是整数")

        # 简化的史莱姆区块计算 (基于 Java 版算法)
        slime_chunks = []
        search_range = 10  # 搜索范围 (区块)

        for x in range(-search_range, search_range):
            for z in range(-search_range, search_range):
                # 史莱姆区块判定算法
                chunk_seed = (
                    seed +
                    int(x * x * 0x4c1906) +
                    int(x * 0x5ac0db) +
                    int(z * z) * 0x4307a7 +
                    int(z * 0x5f24f) ^ 0x3ad8025f
                )

                # 使用 Java Random 算法
                chunk_seed = (chunk_seed ^ 0x5deece66d) & ((1 << 48) - 1)
                random_value = (chunk_seed * 0x5deece66d + 0xb) & ((1 << 48) - 1)
                random_value = (random_value >> 17) % 10

                if random_value == 0:
                    slime_chunks.append((x, z))

        if not slime_chunks:
            return MessageEventResult().message(f"在附近 {search_range} 区块内未找到史莱姆区块")

        # 限制显示数量
        display_chunks = slime_chunks[:10]
        result = f"Minecraft {version} 种子 {seed} 的史莱姆区块:\n"
        result += "\n".join([f"区块 ({x}, {z})" for x, z in display_chunks])

        if len(slime_chunks) > 10:
            result += f"\n... 还有 {len(slime_chunks) - 10} 个区块"

        return MessageEventResult().message(result)

    @star_receiver(command="sf")
    async def handle_sf(self, event: AstrMessageEvent) -> MessageEventResult:
        """slimefinder 的缩写"""
        return await self.handle_slimefinder(event)

    @star_receiver()
    async def handle_message(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理所有消息 (用于消息记录和广告检测)"""
        # 记录消息
        self._record_message(event)

        # 检查是否是群消息
        if not event.message_obj.group_id:
            return MessageEventResult()

        group_id = str(event.message_obj.group_id)

        # 检查用户是否被封禁
        user_id = str(event.message_obj.sender.user_id)
        if self._is_user_banned(group_id, user_id):
            # 自动踢出封禁用户
            await self._kick_user(event, user_id)
            return MessageEventResult().stop_event()

        # 检查是否启用广告拦截
        adban_key = self._get_adban_key(group_id)
        if self.db.get(adban_key, False):
            # 计算广告评分
            score = self._calculate_ad_score(event.message_str)

            # 评分阈值: 6 分以上视为广告
            if score >= 6:
                # 撤回消息
                await self._recall_message(event, event.message_obj.message_id)

                # 禁言 10 分钟
                await self._mute_user(event, user_id, 600)

                logger.info(f"检测到广告 (评分: {score}), 已撤回并禁言用户 {user_id}")
                return MessageEventResult().stop_event()

        return MessageEventResult()

    @star_receiver(event_type="member_increase")
    async def handle_member_join(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理成员加群事件"""
        if not event.message_obj.group_id:
            return MessageEventResult()

        group_id = str(event.message_obj.group_id)
        user_id = str(event.message_obj.user_id)

        # 检查是否在封禁列表
        if self._is_user_banned(group_id, user_id):
            # 自动踢出
            await self._kick_user(event, user_id)
            logger.info(f"封禁用户 {user_id} 尝试加入群 {group_id}，已自动踢出")
            return MessageEventResult().stop_event()

        # 发送欢迎消息
        key = self._get_welcome_key(group_id)
        welcome_data = self.db.get(key)

        if welcome_data and welcome_data.get('enabled'):
            content = self._replace_placeholders(welcome_data.get('content', ''), event)
            return MessageEventResult().message(content)

        return MessageEventResult()


# 导入 asyncio (用于延迟操作)
import asyncio
