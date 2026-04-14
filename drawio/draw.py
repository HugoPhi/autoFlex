import graphviz

def generate_compact_svg():
    # 创建主图
    dot = graphviz.Digraph('Pruning', format='svg')
    
    # 紧凑布局设置
    dot.attr(rankdir='LR', nodesep='0.3', ranksep='0.6', splines='line')
    # 设置全局默认字体为宋体
    dot.attr(fontname='Songti SC', fontsize='16')
    
    # 顶部总标题 (使用 HTML label 区分中英文字体)
    # 中文：宋体-简，英文/公式：Times New Roman
    main_label = (
        '<<table border="0" cellborder="0" cellspacing="0">'
        '<tr><td><font face="Songti SC">nginx 偏序集上的单查询剪枝（诱导子图）</font></td></tr>'
        '<tr><td><font face="Times New Roman">|<i>C</i>|=96, '
        '<font face="Songti SC">查询</font>=<i>C</i><sub>81</sub>, '
        '|<i>anc</i>(<i>c</i>)|=16, |<i>desc</i>(<i>c</i>)|=12</font></td></tr>'
        '</table>>'
    )
    dot.attr(label=main_label, labelloc='t')

    # 统一节点大小
    unified_size = '0.55'

    # 定义查询节点样式 (橙色)
    query_style = {
        'shape': 'doublecircle', 
        'style': 'filled', 
        'fillcolor': '#ffe0b2', 
        'color': '#f57c00', 
        'penwidth': '2.0', 
        'width': unified_size, 
        'height': unified_size,
        'label': '',
        'fixedsize': 'true'
    }
    
    # 灰度定义
    grays = ['#424242', '#757575', '#9e9e9e', '#bdbdbd', '#e0e0e0', '#f5f5f5']

    def add_case(name, html_label):
        with dot.subgraph(name=f'cluster_{name}') as c:
            # 紧凑的子图边距，设置子图标签字体
            c.attr(label=html_label, style='rounded,dashed', color='#cccccc', margin='8')

            # 通用节点属性 (灰色节点)
            node_attr = {
                'style': 'filled', 
                'shape': 'circle', 
                'width': unified_size, 
                'height': unified_size, 
                'label': '',
                'fixedsize': 'true'
            }

            # 定义节点层级结构
            nodes = [
                ('1_1', grays[0]), ('1_2', grays[1]),
                ('2_1', grays[1]), ('2_2', grays[2]), ('2_3', grays[0]), ('2_4', grays[1]),
                ('3_1', grays[3]), ('3_2', grays[3]), ('3_3', grays[2])
            ]
            for n_id, color in nodes:
                c.node(f'{name}_{n_id}', fillcolor=color, **node_attr)

            c.node(f'{name}_Q', **query_style)

            desc_nodes = [
                ('4_1', grays[3]), ('4_2', grays[4]), ('4_3', grays[3]),
                ('5_1', grays[5]), ('5_2', grays[5]), ('5_3', grays[5]), ('5_4', grays[5]),
                ('6_1', grays[5]), ('6_2', grays[5])
            ]
            for n_id, color in desc_nodes:
                c.node(f'{name}_{n_id}', fillcolor=color, **node_attr)

            # 建立连接关系
            edge_attr = {'color': '#999999', 'arrowsize': '0.7', 'penwidth': '1.2'}
            edges = [
                ('1_1', '2_1'), ('1_2', '2_4'),
                ('2_1', '3_1'), ('2_2', '3_1'), ('2_2', '3_2'), ('2_3', '3_2'), ('2_4', '3_3'),
                ('3_1', 'Q'), ('3_2', 'Q'), ('3_3', 'Q'),
                ('Q', '4_1'), ('Q', '4_2'), ('Q', '4_3'),
                ('4_1', '5_1'), ('4_2', '5_2'), ('4_2', '5_3'), ('4_3', '5_4'),
                ('5_1', '6_1'), ('5_2', '6_1'), ('5_3', '6_2'), ('5_4', '6_2')
            ]
            for u, v in edges:
                c.edge(f'{name}_{u}', f'{name}_{v}', **edge_attr)

    # 情况 A 和 情况 B 的单行标签 (中英文字体混排)
    # 情况 A: g(c) < 0, C <- C \ desc(c)
    label_a = (
        '<<font face="Songti SC">情况一：</font>'
        '<font face="Times New Roman"><i>g</i>(<i>c</i>) &lt; 0, <i>C</i> &larr; <i>C</i> \ <i>desc</i>(<i>c</i>)</font>>'
    )
    # 情况 B: g(c) >= 0, C <- C \ anc(c)
    label_b = (
        '<<font face="Songti SC">情况二：</font>'
        '<font face="Times New Roman"><i>g</i>(<i>c</i>) &ge; 0, <i>C</i> &larr; <i>C</i> \ <i>anc</i>(<i>c</i>)</font>>'
    )

    # 添加两个子图
    add_case('CaseB', label_b)
    add_case('CaseA', label_a)

    # 保存文件
    dot.render('compact_poset_pruning_cn', cleanup=True)
    print("完成！SVG 已保存为 compact_poset_pruning_cn.svg")

if __name__ == "__main__":
    generate_compact_svg()