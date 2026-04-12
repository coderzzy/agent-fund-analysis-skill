#!/usr/bin/env python3
"""
基金数据分析脚本
用于解析天天基金网数据并生成HTML分析报告
"""

import re
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Any
import numpy as np


class FundDataParser:
    """基金数据解析器"""
    
    def __init__(self, js_content: str):
        self.js_content = js_content
        self.data = {}
        
    def parse(self) -> Dict:
        """解析JS内容提取关键数据"""
        # 提取基金基本信息
        self.data['name'] = self._extract_string('fS_name')
        self.data['code'] = self._extract_string('fS_code')
        self.data['source_rate'] = self._extract_string('fund_sourceRate')
        self.data['rate'] = self._extract_string('fund_Rate')
        self.data['min_amount'] = self._extract_string('fund_minsg')
        
        # 提取收益率
        self.data['return_1y'] = self._extract_float('syl_1y')
        self.data['return_6m'] = self._extract_float('syl_6y')
        self.data['return_3m'] = self._extract_float('syl_3y')
        self.data['return_1m'] = self._extract_float('syl_1y')
        
        # 提取净值走势数据
        self.data['net_worth_trend'] = self._extract_json('Data_netWorthTrend')
        self.data['ac_worth_trend'] = self._extract_array('Data_acWorthTrend')
        
        return self.data
    
    def _extract_string(self, var_name: str) -> str:
        """提取字符串变量"""
        pattern = rf'var {var_name}\s*=\s*"([^"]*)"'
        match = re.search(pattern, self.js_content)
        return match.group(1) if match else ''
    
    def _extract_float(self, var_name: str) -> float:
        """提取浮点数变量"""
        pattern = rf'var {var_name}\s*=\s*"([^"]*)"'
        match = re.search(pattern, self.js_content)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return 0.0
        return 0.0
    
    def _extract_json(self, var_name: str) -> List[Dict]:
        """提取JSON数组"""
        pattern = rf'var {var_name}\s*=\s*(\[.*?\]);'
        match = re.search(pattern, self.js_content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return []
        return []
    
    def _extract_array(self, var_name: str) -> List[List]:
        """提取二维数组"""
        pattern = rf'var {var_name}\s*=\s*(\[\[.*?\]\]);'
        match = re.search(pattern, self.js_content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                return []
        return []


class FundAnalyzer:
    """基金数据分析器"""
    
    def __init__(self, data: Dict):
        self.data = data
        self.df = self._prepare_dataframe()
        
    def _prepare_dataframe(self) -> List[Dict]:
        """准备数据列表"""
        net_worth = self.data.get('net_worth_trend', [])
        records = []
        for item in net_worth:
            records.append({
                'date': datetime.fromtimestamp(item['x'] / 1000),
                'net_worth': item['y'],
                'daily_return': item.get('equityReturn', 0)
            })
        return records
    
    def analyze_monthly_returns(self) -> Dict:
        """按月分析收益，涨幅和跌幅分开统计"""
        # 按月份分组计算月收益率
        monthly_data = {}
        for record in self.df:
            month_key = record['date'].strftime('%Y-%m')
            if month_key not in monthly_data:
                monthly_data[month_key] = {'values': [], 'date': record['date']}
            monthly_data[month_key]['values'].append(record['net_worth'])
        
        # 计算每个月的收益率
        monthly_returns = {}
        for month, data in monthly_data.items():
            values = data['values']
            if len(values) > 1:
                ret = (values[-1] - values[0]) / values[0] * 100
                monthly_returns[month] = {
                    'return': ret,
                    'start_date': data['date'].strftime('%Y-%m-%d')
                }
        
        # 分开统计涨幅和跌幅
        positive_returns = [v['return'] for v in monthly_returns.values() if v['return'] > 0]
        negative_returns = [v['return'] for v in monthly_returns.values() if v['return'] < 0]
        
        result = {
            'monthly_details': monthly_returns,
            'positive': {
                'count': len(positive_returns),
                'mean': float(np.mean(positive_returns)) if positive_returns else 0,
                'median': float(np.median(positive_returns)) if positive_returns else 0,
                'max': float(np.max(positive_returns)) if positive_returns else 0,
                'returns': positive_returns
            },
            'negative': {
                'count': len(negative_returns),
                'mean': float(np.mean(negative_returns)) if negative_returns else 0,
                'median': float(np.median(negative_returns)) if negative_returns else 0,
                'min': float(np.min(negative_returns)) if negative_returns else 0,
                'returns': negative_returns
            }
        }
        
        return result
    
    def analyze_multi_period_returns(self) -> Dict:
        """
        按不同持有周期分析涨跌幅（使用不重叠滑动窗口）
        周期：1天、3天、1周(7天)、1月(30天)、半年(180天)、一年(365天)
        
        算法：使用不重叠的滑动窗口，例如1年周期，从第0天开始，然后是第365天、第730天...
        这样4年历史只有4个1年样本，更符合实际投资场景。
        """
        periods = {
            '1天': 1,
            '3天': 3,
            '1周': 7,
            '1月': 30,
            '半年': 180,
            '1年': 365
        }
        
        result = {}
        
        for period_name, days in periods.items():
            returns = []
            
            # 使用不重叠窗口：从0开始，每次跳跃days天
            i = 0
            while i + days < len(self.df):
                start_value = self.df[i]['net_worth']
                end_value = self.df[i + days]['net_worth']
                total_return = (end_value - start_value) / start_value * 100
                returns.append(total_return)
                i += days  # 跳跃days天，确保窗口不重叠
            
            if returns:
                # 分开统计正收益和负收益
                positive_returns = [r for r in returns if r > 0]
                negative_returns = [r for r in returns if r < 0]
                
                result[period_name] = {
                    'positive': {
                        'count': len(positive_returns),
                        'mean': float(np.mean(positive_returns)) if positive_returns else 0,
                        'median': float(np.median(positive_returns)) if positive_returns else 0,
                        'max': float(np.max(positive_returns)) if positive_returns else 0
                    },
                    'negative': {
                        'count': len(negative_returns),
                        'mean': float(np.mean(negative_returns)) if negative_returns else 0,
                        'median': float(np.median(negative_returns)) if negative_returns else 0,
                        'min': float(np.min(negative_returns)) if negative_returns else 0
                    },
                    'total_samples': len(returns)
                }
            else:
                result[period_name] = {
                    'positive': {'count': 0, 'mean': 0, 'median': 0, 'max': 0},
                    'negative': {'count': 0, 'mean': 0, 'median': 0, 'min': 0},
                    'total_samples': 0
                }
        
        return result
    
    def find_return_periods(self) -> Dict:
        """
        分析收益周期和反转天数
        
        包含两部分分析：
        1. 为每一天找到从该天开始的最长正/负收益周期
        2. 计算反转天数：从正收益状态转为负收益状态（或反之）的平均时间
        
        反转天数定义：
        - 正转负：从某一天开始持有收益为正，到第一次出现持有收益为负的间隔天数
        - 负转正：从某一天开始持有收益为负，到第一次出现持有收益为正的间隔天数
        """
        if len(self.df) < 2:
            return {
                'positive': {
                    'max_period': {'days': 0, 'start_date': None, 'end_date': None, 'return': 0},
                    'avg_period': {'days': 0},
                    'median_period': {'days': 0}
                },
                'negative': {
                    'max_period': {'days': 0, 'start_date': None, 'end_date': None, 'return': 0},
                    'avg_period': {'days': 0},
                    'median_period': {'days': 0}
                },
                'reversal': {
                    'positive_to_negative': {'avg_days': 0, 'median_days': 0, 'count': 0},
                    'negative_to_positive': {'avg_days': 0, 'median_days': 0, 'count': 0}
                }
            }
        
        positive_periods = []
        negative_periods = []
        
        # 用于计算反转天数
        pos_to_neg_days = []  # 正转负的天数
        neg_to_pos_days = []  # 负转正的天数
        
        for start_idx in range(len(self.df)):
            start_value = self.df[start_idx]['net_worth']
            start_date = self.df[start_idx]['date']
            
            # 找从当前点开始的最长正收益周期
            best_positive = None
            # 找从当前点开始的最长负收益周期
            best_negative = None
            
            # 找第一次反转点
            first_negative = None  # 第一次出现负收益
            first_positive = None  # 第一次出现正收益
            
            for end_idx in range(start_idx + 1, len(self.df)):
                end_value = self.df[end_idx]['net_worth']
                end_date = self.df[end_idx]['date']
                
                total_return = (end_value - start_value) / start_value * 100
                days = (end_date - start_date).days
                
                period_info = {
                    'start_idx': start_idx,
                    'end_idx': end_idx,
                    'days': days,
                    'start_date': start_date.strftime('%Y-%m-%d'),
                    'end_date': end_date.strftime('%Y-%m-%d'),
                    'return': total_return
                }
                
                # 只要是正收益就更新（找最长的）
                if total_return > 0:
                    best_positive = period_info
                    # 记录第一次出现正收益（用于负转正的计算）
                    if first_positive is None:
                        first_positive = days
                # 只要是负收益就更新（找最长的）
                elif total_return < 0:
                    best_negative = period_info
                    # 记录第一次出现负收益（用于正转负的计算）
                    if first_negative is None:
                        first_negative = days
            
            # 记录从当前点开始的最长正收益周期（如果存在）
            if best_positive is not None:
                positive_periods.append(best_positive)
            
            # 记录从当前点开始的最长负收益周期（如果存在）
            if best_negative is not None:
                negative_periods.append(best_negative)
            
            # 计算反转天数
            # 如果当前点既有正收益可能又有负收益可能
            if first_negative is not None:
                pos_to_neg_days.append(first_negative)
            if first_positive is not None:
                neg_to_pos_days.append(first_positive)
        
        # 统计正收益周期
        positive_result = self._calculate_period_stats(positive_periods)
        # 统计负收益周期
        negative_result = self._calculate_period_stats(negative_periods)
        
        # 统计反转天数
        reversal_stats = {
            'positive_to_negative': {
                'avg_days': float(np.mean(pos_to_neg_days)) if pos_to_neg_days else 0,
                'median_days': float(np.median(pos_to_neg_days)) if pos_to_neg_days else 0,
                'max_days': float(np.max(pos_to_neg_days)) if pos_to_neg_days else 0,
                'count': len(pos_to_neg_days)
            },
            'negative_to_positive': {
                'avg_days': float(np.mean(neg_to_pos_days)) if neg_to_pos_days else 0,
                'median_days': float(np.median(neg_to_pos_days)) if neg_to_pos_days else 0,
                'max_days': float(np.max(neg_to_pos_days)) if neg_to_pos_days else 0,
                'count': len(neg_to_pos_days)
            }
        }
        
        return {
            'positive': positive_result,
            'negative': negative_result,
            'reversal': reversal_stats
        }
    
    def _calculate_period_stats(self, periods: List[Dict]) -> Dict:
        """计算周期统计信息"""
        if not periods:
            return {
                'max_period': {'days': 0, 'start_date': None, 'end_date': None, 'return': 0},
                'avg_period': {'days': 0},
                'median_period': {'days': 0},
                'total_periods': 0,
                'distribution': {},
                'warning_days': 0
            }
        
        # 找出最大周期
        max_period = max(periods, key=lambda x: x['days'])
        
        # 计算统计值
        all_days = [p['days'] for p in periods]
        avg_days = np.mean(all_days)
        median_days = np.median(all_days)
        
        # 计算分布（按天数分段）
        distribution = self._calculate_period_distribution(all_days)
        
        # 计算预警天数（基于百分位数）
        # 使用25%分位数作为预警线：25%的正收益周期在这个天数内结束
        warning_days = np.percentile(all_days, 25)
        
        # 计算不同持有时间的平均收益
        return_by_holding = self._calculate_return_by_holding_period(periods)
        
        return {
            'max_period': {
                'days': int(max_period['days']),
                'start_date': max_period['start_date'],
                'end_date': max_period['end_date'],
                'return': float(max_period['return'])
            },
            'avg_period': {
                'days': float(avg_days)
            },
            'median_period': {
                'days': float(median_days)
            },
            'total_periods': len(periods),
            'distribution': distribution,
            'warning_days': float(warning_days),
            'return_by_holding': return_by_holding
        }
    
    def _calculate_period_distribution(self, all_days: List[int]) -> Dict:
        """计算周期天数分布"""
        # 定义时间段
        ranges = [
            (0, 7, '1周内'),
            (7, 30, '1周-1月'),
            (30, 90, '1-3月'),
            (90, 180, '3-6月'),
            (180, 365, '6月-1年'),
            (365, 730, '1-2年'),
            (730, float('inf'), '2年以上')
        ]
        
        distribution = {}
        for min_days, max_days, label in ranges:
            count = sum(1 for d in all_days if min_days <= d < max_days)
            percentage = count / len(all_days) * 100 if all_days else 0
            distribution[label] = {
                'count': count,
                'percentage': float(percentage)
            }
        
        return distribution
    
    def _calculate_return_by_holding_period(self, periods: List[Dict]) -> Dict:
        """计算不同持有时间的平均收益"""
        # 按持有时间分组
        short_term = []  # < 30天
        medium_term = []  # 30-180天
        long_term = []  # > 180天
        
        for p in periods:
            days = p['days']
            ret = p['return']
            if days < 30:
                short_term.append(ret)
            elif days < 180:
                medium_term.append(ret)
            else:
                long_term.append(ret)
        
        return {
            'short_term': {
                'days_range': '< 30天',
                'avg_return': float(np.mean(short_term)) if short_term else 0,
                'count': len(short_term)
            },
            'medium_term': {
                'days_range': '30-180天',
                'avg_return': float(np.mean(medium_term)) if medium_term else 0,
                'count': len(medium_term)
            },
            'long_term': {
                'days_range': '> 180天',
                'avg_return': float(np.mean(long_term)) if long_term else 0,
                'count': len(long_term)
            }
        }
    
    def calculate_max_drawdown(self) -> Dict:
        """计算最大回撤"""
        if not self.df:
            return {'max_drawdown': 0, 'start_date': None, 'end_date': None}
        
        max_drawdown = 0
        peak_value = self.df[0]['net_worth']
        peak_date = self.df[0]['date']
        start_date = None
        end_date = None
        
        for record in self.df:
            if record['net_worth'] > peak_value:
                peak_value = record['net_worth']
                peak_date = record['date']
            
            drawdown = (peak_value - record['net_worth']) / peak_value * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
                start_date = peak_date
                end_date = record['date']
        
        return {
            'max_drawdown': max_drawdown,
            'start_date': start_date.strftime('%Y-%m-%d') if start_date else None,
            'end_date': end_date.strftime('%Y-%m-%d') if end_date else None
        }
    
    def calculate_volatility(self) -> Dict:
        """计算波动率"""
        if len(self.df) < 2:
            return {'daily': 0, 'annualized': 0}
        
        daily_returns = []
        for i in range(1, len(self.df)):
            ret = (self.df[i]['net_worth'] - self.df[i-1]['net_worth']) / self.df[i-1]['net_worth']
            daily_returns.append(ret)
        
        daily_vol = np.std(daily_returns) * 100
        annualized_vol = daily_vol * np.sqrt(252)
        
        return {
            'daily': float(daily_vol),
            'annualized': float(annualized_vol)
        }
    
    def analyze_net_worth_by_period(self) -> Dict:
        """
        多周期净值分析
        分析过去1个月、半年、1年、3年、成立以来的净值统计
        """
        if not self.df:
            return {}
        
        end_date = self.df[-1]['date']
        
        periods = {
            '1个月': 30,
            '半年': 180,
            '1年': 365,
            '3年': 365 * 3
        }
        
        result = {}
        
        # 计算各个周期的统计
        for period_name, days in periods.items():
            start_date = end_date - timedelta(days=days)
            period_data = [r for r in self.df if r['date'] >= start_date]
            
            if period_data:
                values = [r['net_worth'] for r in period_data]
                result[period_name] = {
                    'mean': float(np.mean(values)),
                    'median': float(np.median(values)),
                    'max': float(np.max(values)),
                    'min': float(np.min(values)),
                    'std': float(np.std(values)),
                    'count': len(values),
                    'start_date': period_data[0]['date'].strftime('%Y-%m-%d'),
                    'end_date': period_data[-1]['date'].strftime('%Y-%m-%d')
                }
        
        # 成立以来（全部数据）
        all_values = [r['net_worth'] for r in self.df]
        result['成立以来'] = {
            'mean': float(np.mean(all_values)),
            'median': float(np.median(all_values)),
            'max': float(np.max(all_values)),
            'min': float(np.min(all_values)),
            'std': float(np.std(all_values)),
            'count': len(all_values),
            'start_date': self.df[0]['date'].strftime('%Y-%m-%d'),
            'end_date': self.df[-1]['date'].strftime('%Y-%m-%d')
        }
        
        return result
    
    def analyze_pressure_zones(self) -> Dict:
        """
        压力指标分析 - 基于净值区间的支撑与压力分析
        
        核心逻辑：
        1. 将净值区间划分为多个档位（基于历史最高最低净值）
        2. 统计每个档位内的上涨/下跌概率
        3. 计算每个档位的平均收益率
        4. 识别支撑位（下跌后反弹概率高的区间）和压力位（上涨后回落概率高的区间）
        """
        if len(self.df) < 30:
            return {}
        
        # 获取净值数据
        values = [r['net_worth'] for r in self.df]
        max_val = max(values)
        min_val = min(values)
        
        if max_val == min_val:
            return {}
        
        # 将净值区间划分为10个档位
        num_zones = 10
        zone_size = (max_val - min_val) / num_zones
        
        zones = []
        for i in range(num_zones):
            zone_min = min_val + i * zone_size
            zone_max = min_val + (i + 1) * zone_size
            zone_mid = (zone_min + zone_max) / 2
            
            # 找到该区间内的所有交易日
            zone_records = [
                (idx, r) for idx, r in enumerate(self.df)
                if zone_min <= r['net_worth'] < zone_max or (i == num_zones - 1 and r['net_worth'] == max_val)
            ]
            
            if not zone_records:
                zones.append({
                    'zone_index': i,
                    'price_range': f"{zone_min:.4f} - {zone_max:.4f}",
                    'mid_price': zone_mid,
                    'days_count': 0,
                    'up_probability': 0,
                    'down_probability': 0,
                    'avg_return_5d': 0,
                    'avg_return_10d': 0,
                    'avg_return_20d': 0,
                    'bounce_probability': 0,  # 反弹概率（从该区间上涨）
                    'fall_probability': 0,    # 回落概率（从该区间下跌）
                    'zone_type': 'neutral'
                })
                continue
            
            # 计算该区间后的未来收益
            future_returns_5d = []
            future_returns_10d = []
            future_returns_20d = []
            up_count = 0
            down_count = 0
            bounce_count = 0  # 反弹次数
            fall_count = 0    # 回落次数
            
            for idx, record in zone_records:
                # 未来5天收益
                if idx + 5 < len(self.df):
                    ret_5d = (self.df[idx + 5]['net_worth'] - record['net_worth']) / record['net_worth'] * 100
                    future_returns_5d.append(ret_5d)
                    if ret_5d > 0:
                        up_count += 1
                        bounce_count += 1
                    else:
                        down_count += 1
                
                # 未来10天收益
                if idx + 10 < len(self.df):
                    ret_10d = (self.df[idx + 10]['net_worth'] - record['net_worth']) / record['net_worth'] * 100
                    future_returns_10d.append(ret_10d)
                
                # 未来20天收益
                if idx + 20 < len(self.df):
                    ret_20d = (self.df[idx + 20]['net_worth'] - record['net_worth']) / record['net_worth'] * 100
                    future_returns_20d.append(ret_20d)
                    if ret_20d < 0:
                        fall_count += 1
            
            total_signals = len(future_returns_5d)
            
            if total_signals > 0:
                up_prob = up_count / total_signals * 100
                down_prob = down_count / total_signals * 100
                bounce_prob = bounce_count / total_signals * 100 if bounce_count > 0 else 0
                fall_prob = fall_count / len(future_returns_20d) * 100 if future_returns_20d and fall_count > 0 else 0
                
                # 判断区间类型
                if up_prob >= 60 and bounce_prob >= 55:
                    zone_type = 'support'  # 支撑位
                elif down_prob >= 60 and fall_prob >= 55:
                    zone_type = 'resistance'  # 压力位
                else:
                    zone_type = 'neutral'
                
                zones.append({
                    'zone_index': i,
                    'price_range': f"{zone_min:.4f} - {zone_max:.4f}",
                    'mid_price': zone_mid,
                    'days_count': len(zone_records),
                    'up_probability': round(up_prob, 1),
                    'down_probability': round(down_prob, 1),
                    'avg_return_5d': round(float(np.mean(future_returns_5d)), 2) if future_returns_5d else 0,
                    'avg_return_10d': round(float(np.mean(future_returns_10d)), 2) if future_returns_10d else 0,
                    'avg_return_20d': round(float(np.mean(future_returns_20d)), 2) if future_returns_20d else 0,
                    'bounce_probability': round(bounce_prob, 1),
                    'fall_probability': round(fall_prob, 1),
                    'zone_type': zone_type
                })
            else:
                zones.append({
                    'zone_index': i,
                    'price_range': f"{zone_min:.4f} - {zone_max:.4f}",
                    'mid_price': zone_mid,
                    'days_count': len(zone_records),
                    'up_probability': 0,
                    'down_probability': 0,
                    'avg_return_5d': 0,
                    'avg_return_10d': 0,
                    'avg_return_20d': 0,
                    'bounce_probability': 0,
                    'fall_probability': 0,
                    'zone_type': 'neutral'
                })
        
        # 识别关键支撑和压力位
        support_zones = [z for z in zones if z['zone_type'] == 'support' and z['days_count'] > 0]
        resistance_zones = [z for z in zones if z['zone_type'] == 'resistance' and z['days_count'] > 0]
        
        # 当前净值位置
        current_price = self.df[-1]['net_worth']
        current_zone_idx = int((current_price - min_val) / zone_size)
        current_zone_idx = min(current_zone_idx, num_zones - 1)
        
        return {
            'zones': zones,
            'support_zones': support_zones,
            'resistance_zones': resistance_zones,
            'current_price': current_price,
            'current_zone_index': current_zone_idx,
            'price_range': {'min': min_val, 'max': max_val},
            'analysis_summary': {
                'support_count': len(support_zones),
                'resistance_count': len(resistance_zones),
                'nearest_support': support_zones[-1] if support_zones and current_zone_idx > support_zones[-1]['zone_index'] else None,
                'nearest_resistance': resistance_zones[0] if resistance_zones and current_zone_idx < resistance_zones[0]['zone_index'] else None
            }
        }
    
    def monthly_analysis(self) -> Dict:
        """月度收益分析"""
        monthly_returns = {}
        
        for record in self.df:
            month_key = record['date'].strftime('%Y-%m')
            if month_key not in monthly_returns:
                monthly_returns[month_key] = []
            monthly_returns[month_key].append(record['net_worth'])
        
        results = {}
        for month, values in monthly_returns.items():
            if len(values) > 1:
                ret = (values[-1] - values[0]) / values[0] * 100
                results[month] = ret
        
        return results


class HTMLReportGenerator:
    """HTML报告生成器"""
    
    def __init__(self, fund_data: Dict, analysis_results: Dict):
        self.fund_data = fund_data
        self.analysis = analysis_results
        
    def generate(self) -> str:
        """生成HTML报告"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>基金分析报告 - {self.fund_data.get('name', '')}</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <script src="https://unpkg.com/html2pdf.js@0.10.1/dist/html2pdf.bundle.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        /* PPT风格 - 横版16:9比例 */
        :root {{
            --slide-width: 297mm;
            --slide-height: 167mm;
            --primary-color: #667eea;
            --secondary-color: #764ba2;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f5f5;
            color: #333;
            line-height: 1.5;
        }}

        /* PPT幻灯片容器 */
        .ppt-container {{
            max-width: var(--slide-width);
            margin: 0 auto;
            padding: 20px;
        }}

        /* 单个幻灯片 - 横版16:9 */
        .slide {{
            width: var(--slide-width);
            height: var(--slide-height);
            background: white;
            margin: 0 auto 30px auto;
            padding: 30px 40px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
            page-break-after: always;
            break-after: page;
            display: flex;
            flex-direction: column;
            position: relative;
            overflow: hidden;
            box-sizing: border-box;
        }}
        
        .slide:last-child {{
            page-break-after: auto;
            break-after: auto;
        }}
        
        /* 幻灯片标题 */
        .slide-header {{
            text-align: center;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 3px solid var(--primary-color);
            flex-shrink: 0;
        }}

        .slide-header h1 {{
            font-size: 32px;
            background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            margin-bottom: 8px;
        }}

        .slide-header h2 {{
            font-size: 24px;
            color: #333;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
        }}

        .slide-header .meta {{
            font-size: 13px;
            color: #666;
            margin-top: 8px;
        }}

        /* 幻灯片内容区 */
        .slide-content {{
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}

        /* 封面幻灯片 */
        .slide-cover {{
            background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
            color: white;
            justify-content: center;
            align-items: center;
            text-align: center;
        }}

        .slide-cover .slide-header {{
            border-bottom: none;
        }}

        .slide-cover h1 {{
            font-size: 42px;
            color: white;
            -webkit-text-fill-color: white;
            margin-bottom: 15px;
        }}

        .slide-cover .meta {{
            color: rgba(255,255,255,0.9);
            font-size: 16px;
        }}

        .slide-cover .disclaimer {{
            background: rgba(255,255,255,0.15);
            border: 1px solid rgba(255,255,255,0.3);
            color: rgba(255,255,255,0.95);
            padding: 15px 25px;
            border-radius: 12px;
            margin-top: 30px;
            font-size: 12px;
            max-width: 85%;
        }}
        
        /* 内容卡片 */
        .content-card {{
            background: #f8f9fa;
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 15px;
        }}

        .content-card h3 {{
            font-size: 16px;
            color: var(--primary-color);
            margin-bottom: 10px;
            padding-bottom: 8px;
            border-bottom: 2px solid #e9ecef;
        }}

        /* 两列布局 */
        .two-column {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}

        /* 信息网格 */
        .info-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px;
            height: 100%;
            align-items: center;
        }}

        .info-item {{
            background: linear-gradient(135deg, #f8f9fa 0%, #e9ecef 100%);
            padding: 25px 15px;
            border-radius: 12px;
            text-align: center;
        }}

        .info-item .label {{
            font-size: 13px;
            color: #666;
            margin-bottom: 10px;
        }}

        .info-item .value {{
            font-size: 28px;
            font-weight: 700;
            color: #333;
        }}

        /* 图表容器 */
        .chart-box {{
            background: white;
            border-radius: 10px;
            padding: 15px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.05);
            flex: 1;
            display: flex;
            flex-direction: column;
        }}

        .chart-container {{
            flex: 1;
            width: 100%;
            min-height: 0;
        }}

        /* 表格样式 */
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }}

        th, td {{
            padding: 8px 6px;
            text-align: center;
            border-bottom: 1px solid #eee;
        }}

        th {{
            background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
            color: white;
            font-weight: 600;
            font-size: 10px;
        }}

        tr:hover {{ background: #f8f9fa; }}

        .positive {{ color: #e74c3c; font-weight: 600; }}
        .negative {{ color: #27ae60; font-weight: 600; }}

        /* 压力指标 */
        .zone-grid {{
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 8px;
        }}

        .zone-item {{
            background: #f8f9fa;
            padding: 10px;
            border-radius: 8px;
            text-align: center;
            font-size: 11px;
        }}

        .zone-support {{ background: #d4edda; }}
        .zone-resistance {{ background: #f8d7da; }}
        .zone-neutral {{ background: #e2e3e5; }}

        /* 洞察高亮 */
        .insight-content {{
            flex: 1;
            overflow-y: auto;
            padding: 15px 20px;
            background: #fafafa;
            border-radius: 12px;
        }}
        
        .insight-content h3 {{
            font-size: 16px;
            color: var(--primary-color);
            margin: 12px 0 8px 0;
            padding-bottom: 6px;
            border-bottom: 2px solid #e9ecef;
        }}
        
        .insight-content h3:first-child {{
            margin-top: 0;
        }}
        
        .insight-content p {{
            font-size: 13px;
            line-height: 1.7;
            color: #333;
            margin-bottom: 8px;
        }}
        
        .insight-content strong {{
            color: var(--primary-color);
        }}

        /* 统计行 */
        .stats-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
            gap: 10px;
            margin: 10px 0;
        }}

        .stat-box {{
            background: #f8f9fa;
            padding: 12px;
            border-radius: 8px;
            text-align: center;
        }}

        .stat-label {{
            font-size: 10px;
            color: #666;
            margin-bottom: 4px;
        }}

        .stat-value {{
            font-size: 16px;
            font-weight: 700;
            color: #333;
        }}

        .current-price-tag {{
            background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
            color: white;
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 600;
            display: inline-block;
            margin-bottom: 15px;
        }}

        .progress-bar {{
            width: 100%;
            height: 6px;
            background: #e9ecef;
            border-radius: 3px;
            overflow: hidden;
            margin-top: 4px;
        }}

        .progress-fill {{
            height: 100%;
            border-radius: 3px;
        }}

        .progress-up {{ background: linear-gradient(90deg, #e74c3c, #c0392b); }}
        .progress-down {{ background: linear-gradient(90deg, #27ae60, #229954); }}
        
        /* 加载遮罩 */
        .loading-overlay {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(255,255,255,0.95);
            z-index: 9999;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            transition: opacity 0.5s ease;
        }}
        
        .loading-overlay.hidden {{ opacity: 0; pointer-events: none; }}
        
        .loading-spinner {{
            width: 50px;
            height: 50px;
            border: 4px solid #f3f3f3;
            border-top: 4px solid var(--primary-color);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-bottom: 20px;
        }}
        
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
        .loading-text {{
            font-size: 14px;
            color: #666;
            text-align: center;
        }}
        .loading-status {{
            font-size: 12px;
            color: #999;
            margin-top: 8px;
        }}
        .status-item {{
            display: inline-flex;
            align-items: center;
            margin: 0 10px;
        }}
        .status-icon {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 6px;
        }}
        .status-pending {{ background: #ccc; }}
        .status-loading {{ background: #f39c12; animation: pulse 1.5s infinite; }}
        .status-done {{ background: #27ae60; }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}
        
        /* PDF导出按钮 */
        .pdf-btn {{
            position: fixed;
            top: 20px;
            right: 20px;
            background: linear-gradient(135deg, var(--primary-color) 0%, var(--secondary-color) 100%);
            color: white;
            border: none;
            padding: 12px 24px;
            border-radius: 25px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
            z-index: 1000;
        }}
        
        .pdf-btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5);
        }}
    </style>
</head>
<body>
    <!-- 加载状态遮罩 -->
    <div class="loading-overlay" id="loadingOverlay">
        <div class="loading-spinner"></div>
        <div class="loading-text">正在加载资源...</div>
        <div class="loading-status">
            <span class="status-item" id="status-echarts">
                <span class="status-icon status-pending"></span>图表库
            </span>
            <span class="status-item" id="status-html2pdf">
                <span class="status-icon status-pending"></span>PDF导出
            </span>
        </div>
    </div>
    
    <button class="pdf-btn" onclick="exportToPDF()" id="pdfBtn" style="display: none;">
        📄 导出PDF
    </button>
    
    <div class="ppt-container" id="report-content">
        <!-- Slide 1: 封面 -->
        <div class="slide slide-cover">
            <div class="slide-header">
                <h1>{self.fund_data.get('name', '')}</h1>
                <div class="meta">
                    基金代码: {self.fund_data.get('code', '')}<br>
                    报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}
                </div>
            </div>
            <div class="disclaimer">
                <strong>⚠️ 免责声明</strong>
                本报告仅供参考和学习使用，不构成任何投资建议。基金投资有风险，过往业绩不代表未来表现。投资者应根据自身风险承受能力谨慎决策，自行承担投资风险。
            </div>
        </div>
        
        <!-- Slide 2: 基金基本信息 -->
        <div class="slide">
            <div class="slide-header">
                <h2>📊 基金基本信息</h2>
            </div>
            <div class="slide-content">
                <div class="info-grid">
                    <div class="info-item">
                        <div class="label">基金代码</div>
                        <div class="value">{self.fund_data.get('code', '')}</div>
                    </div>
                    <div class="info-item">
                        <div class="label">当前费率</div>
                        <div class="value">{self.fund_data.get('rate', '')}%</div>
                    </div>
                    <div class="info-item">
                        <div class="label">最小申购</div>
                        <div class="value">{self.fund_data.get('min_amount', '')}元</div>
                    </div>
                    <div class="info-item">
                        <div class="label">数据天数</div>
                        <div class="value">{len(self.fund_data.get('net_worth_trend', []))}天</div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Slide 3: 累计净值走势 -->
        <div class="slide">
            <div class="slide-header">
                <h2>📈 累计净值走势</h2>
                <div class="meta">展示基金成立以来累计净值的历史走势</div>
            </div>
            <div class="slide-content">
                <div class="chart-box">
                    <div id="trendChart" class="chart-container"></div>
                </div>
            </div>
        </div>
        
        <!-- Slide 4: 净值统计分析 -->
        <div class="slide">
            <div class="slide-header">
                <h2>📊 净值统计分析</h2>
                <div class="meta">统计不同时间周期内净值的平均值、中位数、最高最低值</div>
            </div>
            <div class="slide-content">
                {self._generate_net_worth_analysis_table()}
            </div>
        </div>
        
        <!-- Slide 5: 压力指标分析 -->
        <div class="slide">
            <div class="slide-header">
                <h2>🎯 压力指标分析</h2>
                <div class="meta">识别支撑位（上涨概率高）和压力位（下跌概率高）</div>
            </div>
            <div class="slide-content">
                {self._generate_pressure_analysis()}
            </div>
        </div>
        
        <!-- Slide 6: 周期涨跌幅分析 -->
        <div class="slide">
            <div class="slide-header">
                <h2>📅 不同间隔周期涨跌幅分析</h2>
                <div class="meta">统计历史上按不同间隔周期持有后的涨跌幅分布</div>
            </div>
            <div class="slide-content">
                {self._generate_multi_period_returns_table()}
            </div>
        </div>
        
        <!-- Slide 7: 收益反转周期分析 -->
        <div class="slide">
            <div class="slide-header">
                <h2>🔄 收益反转周期分析</h2>
                <div class="meta">分析正收益持续周期及反转规律</div>
            </div>
            <div class="slide-content">
                {self._generate_positive_periods_table()}
            </div>
        </div>
        
        <!-- Slide 8: 月度收益分析 -->
        <div class="slide">
            <div class="slide-header">
                <h2>📆 月度收益分析</h2>
                <div class="meta">月度收益分布及季节性规律</div>
            </div>
            <div class="slide-content">
                {self._generate_monthly_returns_table()}
                <div class="chart-box" style="margin-top: 20px;">
                    <div id="monthlyChart" class="chart-container"></div>
                </div>
            </div>
        </div>
        
        <!-- Slide 9: 数据洞察 (第1页) -->
        <div class="slide">
            <div class="slide-header">
                <h2>💡 数据洞察 (1/2)</h2>
                <div class="meta">基于数据分析的投资建议 - 基金概况与走势分析</div>
            </div>
            <div class="slide-content">
                <div class="insight-content" id="insights-page1">
                    <p style="color: #666; text-align: center; padding: 40px;">等待Agent解读...</p>
                </div>
            </div>
        </div>
        
        <!-- Slide 10: 数据洞察 (第2页) -->
        <div class="slide">
            <div class="slide-header">
                <h2>💡 数据洞察 (2/2)</h2>
                <div class="meta">基于数据分析的投资建议 - 风险提示与投资策略</div>
            </div>
            <div class="slide-content">
                <div class="insight-content" id="insights-page2">
                    <p style="color: #666; text-align: center; padding: 40px;">等待Agent解读...</p>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        // PDF导出功能 - 使用浏览器打印，自动设置横向布局
        function exportToPDF() {{
            // 添加打印样式
            const printStyle = document.createElement('style');
            printStyle.id = 'print-style';
            printStyle.textContent = `
                @media print {{
                    @page {{
                        size: 297mm 167mm;
                        margin: 0;
                    }}
                    body {{
                        background: white;
                        margin: 0;
                        padding: 0;
                        -webkit-print-color-adjust: exact !important;
                        print-color-adjust: exact !important;
                    }}
                    .ppt-container {{
                        padding: 0;
                        margin: 0;
                        max-width: none;
                    }}
                    .slide {{
                        width: 297mm;
                        height: 167mm;
                        margin: 0;
                        padding: 30px 40px;
                        box-shadow: none;
                        page-break-after: always;
                        break-after: page;
                        box-sizing: border-box;
                        background: white;
                    }}
                    .slide-cover {{
                        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
                        -webkit-print-color-adjust: exact !important;
                        print-color-adjust: exact !important;
                    }}
                    .slide:last-child {{
                        page-break-after: auto;
                        break-after: auto;
                    }}
                    .pdf-btn, .loading-overlay {{
                        display: none !important;
                    }}
                }}
            `;
            document.head.appendChild(printStyle);
            
            // 显示提示
            const btn = document.querySelector('.pdf-btn');
            const originalText = btn.innerHTML;
            btn.innerHTML = '⏳ 准备打印...';
            
            // 延迟执行打印，确保样式应用
            setTimeout(() => {{
                // 调用打印，浏览器会自动使用横向布局
                window.print();
                
                // 恢复按钮
                btn.innerHTML = originalText;
                
                // 打印完成后移除样式
                setTimeout(() => {{
                    const style = document.getElementById('print-style');
                    if (style) {{
                        document.head.removeChild(style);
                    }}
                }}, 1000);
            }}, 200);
        }}
        
        // 资源加载状态检测
        const loadStatus = {{
            echarts: false,
            html2pdf: false
        }};
        
        function updateStatus(name, loaded) {{
            const statusEl = document.getElementById('status-' + name);
            if (statusEl) {{
                const icon = statusEl.querySelector('.status-icon');
                if (loaded) {{
                    icon.className = 'status-icon status-done';
                    loadStatus[name] = true;
                }} else {{
                    icon.className = 'status-icon status-loading';
                }}
            }}
        }}
        
        function checkAllLoaded() {{
            if (loadStatus.echarts && loadStatus.html2pdf) {{
                // 所有资源加载完成
                setTimeout(() => {{
                    const overlay = document.getElementById('loadingOverlay');
                    const content = document.getElementById('report-content');
                    const pdfBtn = document.getElementById('pdfBtn');
                    
                    if (overlay) overlay.classList.add('hidden');
                    if (content) content.style.opacity = '1';
                    if (pdfBtn) pdfBtn.style.display = 'block';
                    
                    // 初始化图表
                    initCharts();
                }}, 500);
            }}
        }}
        
        // 检测 echarts 加载
        function checkEcharts() {{
            if (typeof echarts !== 'undefined') {{
                updateStatus('echarts', true);
                checkAllLoaded();
            }} else {{
                updateStatus('echarts', false);
                setTimeout(checkEcharts, 100);
            }}
        }}
        
        // 检测 html2pdf 加载
        function checkHtml2pdf() {{
            if (typeof html2pdf !== 'undefined') {{
                updateStatus('html2pdf', true);
                checkAllLoaded();
            }} else {{
                updateStatus('html2pdf', false);
                setTimeout(checkHtml2pdf, 100);
            }}
        }}
        
        // 页面加载完成后开始检测
        window.addEventListener('load', function() {{
            checkEcharts();
            checkHtml2pdf();
            
            // 超时处理（10秒后强制显示）
            setTimeout(() => {{
                const overlay = document.getElementById('loadingOverlay');
                if (overlay && !overlay.classList.contains('hidden')) {{
                    console.warn('资源加载超时，强制显示页面');
                    overlay.classList.add('hidden');
                    document.getElementById('report-content').style.opacity = '1';
                    document.getElementById('pdfBtn').style.display = 'block';
                    initCharts();
                }}
            }}, 10000);
        }});
        
        // 初始化图表函数
        function initCharts() {{
            try {{
                // 净值走势图
                const trendChart = echarts.init(document.getElementById('trendChart'));
                const trendData = {self._get_trend_chart_data()};
                trendChart.setOption({{
                    tooltip: {{
                        trigger: 'axis',
                        backgroundColor: 'rgba(255,255,255,0.95)',
                        borderColor: '#667eea',
                        borderWidth: 1,
                        textStyle: {{ color: '#333' }},
                        formatter: function(params) {{
                            const date = new Date(params[0].value[0]);
                            return '<strong>' + date.toLocaleDateString() + '</strong><br/>净值: ' + params[0].value[1].toFixed(4);
                        }}
                    }},
                    grid: {{
                        left: '3%',
                        right: '4%',
                        bottom: '15%',
                        top: '10%',
                        containLabel: true
                    }},
                    dataZoom: [
                        {{
                            type: 'inside',
                            start: 0,
                            end: 100
                        }},
                        {{
                            start: 0,
                            end: 100,
                            height: 30,
                            bottom: 10
                        }}
                    ],
                    xAxis: {{
                        type: 'time',
                        boundaryGap: false,
                        axisLabel: {{
                            formatter: '{{yyyy}}-{{MM}}',
                            color: '#666'
                        }}
                    }},
                    yAxis: {{
                        type: 'value',
                        scale: true,
                        axisLabel: {{ color: '#666' }},
                        splitLine: {{ lineStyle: {{ color: '#eee' }} }}
                    }},
                    series: [{{
                        name: '累计净值',
                        type: 'line',
                        data: trendData,
                        smooth: true,
                        symbol: 'none',
                        lineStyle: {{ 
                            width: 3,
                            color: new echarts.graphic.LinearGradient(0, 0, 1, 0, [
                                {{ offset: 0, color: '#667eea' }},
                                {{ offset: 1, color: '#764ba2' }}
                            ])
                        }},
                        areaStyle: {{
                            color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                                {{ offset: 0, color: 'rgba(102, 126, 234, 0.3)' }},
                                {{ offset: 1, color: 'rgba(102, 126, 234, 0.05)' }}
                            ])
                        }}
                    }}]
                }});
                
                // 月度收益图
                const monthlyChart = echarts.init(document.getElementById('monthlyChart'));
                const monthlyData = {self._get_monthly_chart_data()};
                monthlyChart.setOption({{
                    tooltip: {{ 
                        trigger: 'axis',
                        backgroundColor: 'rgba(255,255,255,0.95)',
                        borderColor: '#667eea',
                        borderWidth: 1,
                        textStyle: {{ color: '#333' }}
                    }},
                    grid: {{
                        left: '3%',
                        right: '4%',
                        bottom: '15%',
                        top: '10%',
                        containLabel: true
                    }},
                    xAxis: {{
                        type: 'category',
                        data: monthlyData.categories,
                        axisLabel: {{ 
                            rotate: 45,
                            color: '#666',
                            fontSize: 10
                        }}
                    }},
                    yAxis: {{ 
                        type: 'value', 
                        name: '收益率(%)',
                        nameTextStyle: {{ color: '#666' }},
                        axisLabel: {{ color: '#666' }},
                        splitLine: {{ lineStyle: {{ color: '#eee' }} }}
                    }},
                    series: [{{
                        name: '月度收益',
                        type: 'bar',
                        data: monthlyData.values,
                        itemStyle: {{
                            color: function(params) {{
                                return params.value >= 0 ? '#e74c3c' : '#27ae60';
                            }},
                            borderRadius: [4, 4, 0, 0]
                        }}
                    }}]
                }});
                
                window.addEventListener('resize', function() {{
                    trendChart.resize();
                    monthlyChart.resize();
                }});
            }} catch (err) {{
                console.error('图表初始化失败:', err);
            }}
        }}
    </script>
</body>
</html>"""
        return html
    
    def _generate_net_worth_analysis_table(self) -> str:
        """生成净值分析表格"""
        net_worth_stats = self.analysis.get('net_worth_stats', {})
        
        if not net_worth_stats:
            return '<p style="color: #999;">暂无数据</p>'
        
        rows = ""
        period_order = ['1个月', '半年', '1年', '3年', '成立以来']
        
        for period in period_order:
            data = net_worth_stats.get(period, {})
            if data and data.get('count', 0) > 0:
                rows += f"""
                    <tr>
                        <td style="padding: 10px; border-bottom: 1px solid #eee; font-weight: 600;">{period}</td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center;">{data.get('mean', 0):.4f}</td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center;">{data.get('median', 0):.4f}</td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center; color: #e74c3c; font-weight: 600;">{data.get('max', 0):.4f}</td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center; color: #27ae60; font-weight: 600;">{data.get('min', 0):.4f}</td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center;">{data.get('std', 0):.4f}</td>
                        <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center; color: #666; font-size: 11px;">{data.get('start_date', '')}<br/>至<br/>{data.get('end_date', '')}</td>
                    </tr>
                """
        
        return f"""
        <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <thead>
                    <tr>
                        <th style="padding: 12px; text-align: left; border-radius: 8px 0 0 0;">时间周期</th>
                        <th style="padding: 12px; text-align: center;">平均值</th>
                        <th style="padding: 12px; text-align: center;">中位数</th>
                        <th style="padding: 12px; text-align: center;">最高值</th>
                        <th style="padding: 12px; text-align: center;">最低值</th>
                        <th style="padding: 12px; text-align: center;">标准差</th>
                        <th style="padding: 12px; text-align: center; border-radius: 0 8px 0 0;">统计区间</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
        """
    
    def _generate_pressure_analysis(self) -> str:
        """生成压力指标分析 - 优化布局，增大表格占比"""
        pressure = self.analysis.get('pressure_zones', {})
        
        if not pressure or not pressure.get('zones'):
            return '<p style="color: #999;">数据不足，无法进行分析</p>'
        
        zones = pressure.get('zones', [])
        current_price = pressure.get('current_price', 0)
        current_zone_idx = pressure.get('current_zone_index', 0)
        summary = pressure.get('analysis_summary', {})
        
        # 生成区间表格 - 优化行高和间距
        zone_rows = ""
        for zone in zones:
            if zone['days_count'] == 0:
                continue
            
            zone_type = zone['zone_type']
            badge_class = f"zone-{zone_type}"
            badge_text = "支撑" if zone_type == 'support' else ("压力" if zone_type == 'resistance' else "中性")
            
            is_current = zone['zone_index'] == current_zone_idx
            row_style = 'background: linear-gradient(90deg, rgba(102,126,234,0.15) 0%, transparent 100%);' if is_current else ''
            current_marker = ' 👈' if is_current else ''
            
            zone_rows += f"""
                <tr style="{row_style}">
                    <td style="padding: 6px 8px; border-bottom: 1px solid #eee; text-align: center;">
                        <span class="zone-badge {badge_class}">{badge_text}</span>{current_marker}
                    </td>
                    <td style="padding: 6px 8px; border-bottom: 1px solid #eee; text-align: center; font-size: 11px;">{zone['price_range']}</td>
                    <td style="padding: 6px 8px; border-bottom: 1px solid #eee; text-align: center; font-size: 11px;">{zone['days_count']}</td>
                    <td style="padding: 6px 8px; border-bottom: 1px solid #eee; text-align: center;">
                        <span class="{'positive' if zone['up_probability'] >= 50 else 'neutral'}" style="font-size: 11px;">{zone['up_probability']}%</span>
                        <div class="progress-bar" style="height: 4px; margin-top: 2px;">
                            <div class="progress-fill progress-up" style="width: {zone['up_probability']}%"></div>
                        </div>
                    </td>
                    <td style="padding: 6px 8px; border-bottom: 1px solid #eee; text-align: center;">
                        <span class="{'negative' if zone['down_probability'] >= 50 else 'neutral'}" style="font-size: 11px;">{zone['down_probability']}%</span>
                        <div class="progress-bar" style="height: 4px; margin-top: 2px;">
                            <div class="progress-fill progress-down" style="width: {zone['down_probability']}%"></div>
                        </div>
                    </td>
                    <td style="padding: 6px 8px; border-bottom: 1px solid #eee; text-align: center; color: {'#e74c3c' if zone['avg_return_5d'] > 0 else '#27ae60'}; font-weight: 600; font-size: 11px;">{zone['avg_return_5d']:+.2f}%</td>
                    <td style="padding: 6px 8px; border-bottom: 1px solid #eee; text-align: center; color: {'#e74c3c' if zone['avg_return_20d'] > 0 else '#27ae60'}; font-weight: 600; font-size: 11px;">{zone['avg_return_20d']:+.2f}%</td>
                </tr>
            """
        
        # 生成关键位分析 - 水平排列合并到顶部
        nearest_support = summary.get('nearest_support')
        nearest_resistance = summary.get('nearest_resistance')
        
        key_levels_html = ""
        if nearest_support:
            key_levels_html += f"""
                <div style="background: linear-gradient(135deg, #d4edda 0%, #c3e6cb 100%); padding: 8px 12px; border-radius: 8px; border-left: 3px solid #27ae60; flex: 1;">
                    <div style="font-size: 10px; color: #666;">最近支撑位</div>
                    <div style="font-size: 13px; font-weight: 600; color: #27ae60;">{nearest_support['price_range']}</div>
                    <div style="font-size: 9px; color: #666;">上涨概率 {nearest_support['up_probability']}%</div>
                </div>
            """
        if nearest_resistance:
            key_levels_html += f"""
                <div style="background: linear-gradient(135deg, #f8d7da 0%, #f5c6cb 100%); padding: 8px 12px; border-radius: 8px; border-left: 3px solid #e74c3c; flex: 1;">
                    <div style="font-size: 10px; color: #666;">最近压力位</div>
                    <div style="font-size: 13px; font-weight: 600; color: #e74c3c;">{nearest_resistance['price_range']}</div>
                    <div style="font-size: 9px; color: #666;">下跌概率 {nearest_resistance['down_probability']}%</div>
                </div>
            """
        
        return f"""
        <div style="display: flex; gap: 12px; margin-bottom: 12px; align-items: center;">
            <div class="current-price-tag" style="margin: 0; padding: 8px 16px; font-size: 14px;">
                当前净值: {current_price:.4f}
            </div>
            {key_levels_html}
        </div>
        
        <div style="overflow-x: auto; flex: 1;">
            <table style="width: 100%; border-collapse: collapse; font-size: 11px;">
                <thead>
                    <tr style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white;">
                        <th style="padding: 8px 6px; text-align: center; border-radius: 6px 0 0 0; font-size: 11px;">类型</th>
                        <th style="padding: 8px 6px; text-align: center; font-size: 11px;">净值区间</th>
                        <th style="padding: 8px 6px; text-align: center; font-size: 11px;">天数</th>
                        <th style="padding: 8px 6px; text-align: center; font-size: 11px;">上涨概率</th>
                        <th style="padding: 8px 6px; text-align: center; font-size: 11px;">下跌概率</th>
                        <th style="padding: 8px 6px; text-align: center; font-size: 11px;">5日收益</th>
                        <th style="padding: 8px 6px; text-align: center; border-radius: 0 6px 0 0; font-size: 11px;">20日收益</th>
                    </tr>
                </thead>
                <tbody>
                    {zone_rows}
                </tbody>
            </table>
        </div>
        
        <div style="margin-top: 10px; padding: 10px 12px; background: #f8f9fa; border-radius: 8px; font-size: 10px; color: #666; line-height: 1.6;">
            <strong style="color: #333;">📌 说明：</strong>
            <strong>支撑位</strong>：上涨概率≥60%适合加仓 | 
            <strong>压力位</strong>：下跌概率≥60%适合减仓 | 
            当前净值区间已标注
        </div>
        """
    
    def _generate_monthly_returns_table(self) -> str:
        """生成月度收益分析表格"""
        monthly = self.analysis.get('monthly_returns', {})
        positive = monthly.get('positive', {})
        negative = monthly.get('negative', {})
        
        return f"""
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 16px;">
            <div style="background: linear-gradient(135deg, #fff5f5 0%, #ffe0e0 100%); padding: 20px; border-radius: 12px; border-left: 4px solid #e74c3c;">
                <h4 style="color: #e74c3c; margin-bottom: 14px; font-size: 15px;">📈 上涨月份统计</h4>
                <div class="stats-row">
                    <div class="stat-box">
                        <div class="stat-label">上涨月数</div>
                        <div class="stat-value" style="color: #e74c3c;">{positive.get('count', 0)}</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">平均涨幅</div>
                        <div class="stat-value" style="color: #e74c3c;">{positive.get('mean', 0):.2f}%</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">中位数</div>
                        <div class="stat-value" style="color: #e74c3c;">{positive.get('median', 0):.2f}%</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">最大涨幅</div>
                        <div class="stat-value" style="color: #e74c3c;">{positive.get('max', 0):.2f}%</div>
                    </div>
                </div>
            </div>
            <div style="background: linear-gradient(135deg, #f0fff4 0%, #e0ffe8 100%); padding: 20px; border-radius: 12px; border-left: 4px solid #27ae60;">
                <h4 style="color: #27ae60; margin-bottom: 14px; font-size: 15px;">📉 下跌月份统计</h4>
                <div class="stats-row">
                    <div class="stat-box">
                        <div class="stat-label">下跌月数</div>
                        <div class="stat-value" style="color: #27ae60;">{negative.get('count', 0)}</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">平均跌幅</div>
                        <div class="stat-value" style="color: #27ae60;">{negative.get('mean', 0):.2f}%</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">中位数</div>
                        <div class="stat-value" style="color: #27ae60;">{negative.get('median', 0):.2f}%</div>
                    </div>
                    <div class="stat-box">
                        <div class="stat-label">最大跌幅</div>
                        <div class="stat-value" style="color: #27ae60;">{negative.get('min', 0):.2f}%</div>
                    </div>
                </div>
            </div>
        </div>
        """
    
    def _generate_positive_periods_table(self) -> str:
        """生成收益周期分析表格（正收益和负收益）"""
        return f"""
        {self._generate_holding_warning_section()}
        """

    def _generate_multi_period_returns_table(self) -> str:
        """生成多周期涨跌幅统计表格"""
        multi_period = self.analysis.get('multi_period_returns', {})
        
        # 构建表格行
        rows = ""
        period_order = ['1天', '3天', '1周', '1月', '半年', '1年']
        
        for period in period_order:
            data = multi_period.get(period, {})
            pos = data.get('positive', {})
            neg = data.get('negative', {})
            total = data.get('total_samples', 0)
            
            rows += f"""
                <tr>
                    <td style="padding: 10px; border-bottom: 1px solid #eee; font-weight: 600;">{period}</td>
                    <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center;">{total}</td>
                    <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center; color: #e74c3c;">{pos.get('count', 0)}</td>
                    <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center; color: #e74c3c;">{pos.get('mean', 0):.2f}%</td>
                    <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center; color: #e74c3c;">{pos.get('median', 0):.2f}%</td>
                    <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center; color: #e74c3c; font-weight: 600;">{pos.get('max', 0):.2f}%</td>
                    <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center; color: #27ae60;">{neg.get('count', 0)}</td>
                    <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center; color: #27ae60;">{neg.get('mean', 0):.2f}%</td>
                    <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center; color: #27ae60;">{neg.get('median', 0):.2f}%</td>
                    <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center; color: #27ae60; font-weight: 600;">{neg.get('min', 0):.2f}%</td>
                </tr>
            """
        
        return f"""
        <div style="overflow-x: auto;">
            <table style="width: 100%; border-collapse: collapse; font-size: 13px;">
                <thead>
                    <tr>
                        <th style="padding: 12px; text-align: left; border-radius: 8px 0 0 0;">间隔周期</th>
                        <th style="padding: 12px; text-align: center;">样本数</th>
                        <th style="padding: 12px; text-align: center;">上涨次数</th>
                        <th style="padding: 12px; text-align: center;">上涨均值</th>
                        <th style="padding: 12px; text-align: center;">上涨中位</th>
                        <th style="padding: 12px; text-align: center;">最大涨幅</th>
                        <th style="padding: 12px; text-align: center;">下跌次数</th>
                        <th style="padding: 12px; text-align: center;">下跌均值</th>
                        <th style="padding: 12px; text-align: center;">下跌中位</th>
                        <th style="padding: 12px; text-align: center; border-radius: 0 8px 0 0;">最大跌幅</th>
                    </tr>
                </thead>
                <tbody>
                    {rows}
                </tbody>
            </table>
        </div>
        """
    
    def _generate_holding_warning_section(self) -> str:
        """生成持有预警信息板块"""
        return_periods = self.analysis.get('return_periods', {})
        reversal = return_periods.get('reversal', {})
        
        # 反转天数数据
        pos_to_neg = reversal.get('positive_to_negative', {})
        neg_to_pos = reversal.get('negative_to_positive', {})
        
        return f"""
        <div style="background: linear-gradient(135deg, #fff9e6 0%, #ffe4b5 100%); padding: 20px; border-radius: 12px; border-left: 4px solid #f39c12;">
            <h3 style="color: #d68910; margin-bottom: 16px; display: flex; align-items: center; font-size: 16px;">
                <span style="font-size: 22px; margin-right: 8px;">⚠️</span>
                持有预警与策略建议
            </h3>
            
            <div style="background: white; padding: 16px; border-radius: 10px; margin-bottom: 16px; border: 2px solid #f39c12;">
                <h4 style="color: #d68910; margin-bottom: 12px; font-size: 14px;">🔄 收益反转天数分析</h4>
                <p style="font-size: 12px; color: #666; margin-bottom: 14px; line-height: 1.6;">
                    从某一天买入开始，持有收益为正/负的状态平均持续多久会发生反转
                </p>
                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px;">
                    <div style="background: linear-gradient(135deg, #ff6b6b 0%, #ee5a5a 100%); color: white; padding: 16px; border-radius: 10px; text-align: center;">
                        <div style="font-size: 26px; font-weight: 700;">{pos_to_neg.get('avg_days', 0):.0f}天</div>
                        <div style="font-size: 12px; margin-top: 4px;">正转负平均天数</div>
                        <div style="font-size: 10px; margin-top: 6px; opacity: 0.9;">中位数: {pos_to_neg.get('median_days', 0):.0f}天 | 最大: {pos_to_neg.get('max_days', 0):.0f}天</div>
                    </div>
                    <div style="background: linear-gradient(135deg, #27ae60 0%, #229954 100%); color: white; padding: 16px; border-radius: 10px; text-align: center;">
                        <div style="font-size: 26px; font-weight: 700;">{neg_to_pos.get('avg_days', 0):.0f}天</div>
                        <div style="font-size: 12px; margin-top: 4px;">负转正平均天数</div>
                        <div style="font-size: 10px; margin-top: 6px; opacity: 0.9;">中位数: {neg_to_pos.get('median_days', 0):.0f}天 | 最大: {neg_to_pos.get('max_days', 0):.0f}天</div>
                    </div>
                </div>
            </div>
            
            <div style="background: white; padding: 14px; border-radius: 10px;">
                <h4 style="color: #d68910; margin-bottom: 10px; font-size: 14px;">📋 持有策略建议</h4>
                <div style="font-size: 12px; line-height: 1.8; color: #333;">
                    <p><strong>🔴 警惕期：</strong>持有 <span style="color: #e74c3c; font-weight: bold;">{pos_to_neg.get('avg_days', 0):.0f}天</span>（正转负平均）后需开始关注</p>
                    <p><strong>🟡 参考：</strong>正转负最大曾持续 <span style="color: #f39c12; font-weight: bold;">{pos_to_neg.get('max_days', 0):.0f}天</span>，负转正最大曾持续 <span style="color: #27ae60; font-weight: bold;">{neg_to_pos.get('max_days', 0):.0f}天</span></p>
                </div>
            </div>
        </div>
        """
    
    def _get_trend_chart_data(self) -> str:
        """获取净值走势图数据"""
        net_worth = self.fund_data.get('net_worth_trend', [])
        data = [[item['x'], item['y']] for item in net_worth]
        return json.dumps(data)
    
    def _get_monthly_chart_data(self) -> str:
        """获取月度图表数据"""
        monthly = self.analysis.get('monthly_returns', {})
        details = monthly.get('monthly_details', {})
        categories = list(details.keys())
        values = [v['return'] for v in details.values()]
        return json.dumps({'categories': categories, 'values': values})


def main():
    parser = argparse.ArgumentParser(description='基金数据分析工具')
    parser.add_argument('--code', required=True, help='基金代码')
    parser.add_argument('--input', required=True, help='输入JS文件路径')
    parser.add_argument('--output', required=True, help='输出HTML文件路径')
    parser.add_argument('--json-output', required=True, help='输出JSON分析结果文件路径')
    args = parser.parse_args()
    
    # 读取JS文件
    with open(args.input, 'r', encoding='utf-8') as f:
        js_content = f.read()
    
    # 解析数据
    parser = FundDataParser(js_content)
    fund_data = parser.parse()
    
    # 分析数据
    analyzer = FundAnalyzer(fund_data)
    monthly_analysis = analyzer.analyze_monthly_returns()
    return_periods = analyzer.find_return_periods()
    multi_period_returns = analyzer.analyze_multi_period_returns()
    net_worth_stats = analyzer.analyze_net_worth_by_period()
    pressure_zones = analyzer.analyze_pressure_zones()
    
    analysis_results = {
        'monthly_returns': monthly_analysis,
        'return_periods': return_periods,
        'multi_period_returns': multi_period_returns,
        'max_drawdown': analyzer.calculate_max_drawdown(),
        'volatility': analyzer.calculate_volatility(),
        'net_worth_stats': net_worth_stats,
        'pressure_zones': pressure_zones
    }
    
    # 保存分析结果JSON（供Agent读取）
    json_output = args.json_output
    with open(json_output, 'w', encoding='utf-8') as f:
        json.dump({
            'fund_info': {
                'name': fund_data.get('name'),
                'code': fund_data.get('code'),
                'rate': fund_data.get('rate'),
                'min_amount': fund_data.get('min_amount')
            },
            'returns': {
                '1月': fund_data.get('return_1m'),
                '3月': fund_data.get('return_3m'),
                '6月': fund_data.get('return_6m'),
                '1年': fund_data.get('return_1y')
            },
            'analysis': analysis_results
        }, f, ensure_ascii=False, indent=2)
    
    print(f"分析结果已保存: {json_output}")
    
    # 生成HTML报告
    report_gen = HTMLReportGenerator(fund_data, analysis_results)
    html_content = report_gen.generate()
    
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"HTML报告已生成: {args.output}")


if __name__ == '__main__':
    main()