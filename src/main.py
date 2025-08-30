from ctypes.wintypes import PSIZE
import string

from colorama import Fore, Back
import networkx as nx
import xml.etree.ElementTree as ET

DEBUGGING = True
prefix = 'src//' if DEBUGGING else '_internal//src//'
inputFile = prefix + 'input.txt'
OUTPUT_FOLDER = 'output//'

nodes = {}
nodeValues = {}
edges = []
edgeValues = {}
nodesPrinted = set()


def filter_graphml(input_file, output_file, keep_nodes=None, keep_edges=None):
    G = nx.read_graphml(input_file)

    if keep_nodes is not None:
        keep_nodes = [f'n{num}' for num in keep_nodes]
        nodes_to_remove = [node for node in G.nodes()
                           if node not in keep_nodes]
        G.remove_nodes_from(nodes_to_remove)

    if keep_edges is not None:
        edges_to_remove = [edge for edge in G.edges(keys=True)
                           if edge[2] not in keep_edges]
        G.remove_edges_from(edges_to_remove)

    for node, data in G.nodes(data=True):
        if 'label' in data:
            data['y:NodeLabel'] = data['label']

    nx.write_graphml(G, output_file)


def shiftTo(lst: list, targetNode):
    if not lst:
        return lst

    min_index = lst.index(targetNode)

    return lst[min_index:] + lst[:min_index]


def removeDuplicateSubsets(list_of_lists):
    sorted_lists = sorted(list_of_lists, key=len, reverse=True)
    result = []
    for current_list in sorted_lists:
        if not any(set(current_list).issubset(set(x)) for x in result):
            result.append(current_list)
    return result


def findAllPathsForGraphML(nodes, pSource, isReversed=False):
    # allPaths = findAllPaths(isReversed, nodes, pSource)
    allPaths = []
    for _, nodeID in enumerate(nodes):
        target = nodeID
        source = pSource
        if target == source or target in nodesPrinted:
            continue
        if isReversed:
            source, target = target, source
        paths = list(nx.all_simple_paths(G, source, target))
        for path in paths:
            for node in path:
                nodesPrinted.add(node)
            # allPaths.append(path)

    # for path in allPaths:
    #     for node in path:
    #         nodesPrinted.add(node)


def show_all_paths(nodes, pSource, html_content, isReversed=False):
    html_content += '<br>'

    nodes_to_work_with = []

    if pSource != -1:
        html_content = add_title_to_html(html_content, nodes, pSource, isReversed)
        nodes_to_work_with.append(pSource)
    else:
        for _, nodeID in enumerate(nodes):
            pSource = nodeID
            nodes_to_work_with.append(pSource)
            
    allPaths = []
    for pSource in nodes_to_work_with:
        allPaths = findAllPaths(allPaths, isReversed, nodes, pSource)

        allPaths = removeDuplicateSubsets(allPaths)
        allPaths = sortAlphabeticallyByJoiningNumericalStringLists(allPaths, nodes)

    for path in allPaths:
        cycleCorrelation, nodesToTraverse, pathLen, hp = initializePrintingNodes(path, False)
        for pathNodeID, nodeID in enumerate(path):
            cycleCorrelation, hp = printNode(path, pathNodeID, pathLen, cycleCorrelation, nodesToTraverse, hp,
                                            ENABLE_NON_CYCLE_PRINTING)
        # print(sp)
        if ENABLE_NON_CYCLE_PRINTING:
            html_content += hp + "</p>"
    return html_content

def add_title_to_html(html_content, nodes, pSource, isReversed):
    # if ENABLE_NON_CYCLE_PRINTING: ### REDUNDANT CHECK
    if not isReversed:
        html_content += f'<h1 style="color:white;">Paths from {nodes[pSource]}</h1>'
        print(f"\nPaths from {nodes[pSource]}")
    else:
        html_content += f'<h1 style="color:white;">Paths leading to {nodes[pSource]}</h1>'
        print(f"\nPaths leading to {nodes[pSource]}")
    return html_content


def findAllPaths(allPaths, isReversed, nodes, pSource):
    for _, nodeID in enumerate(nodes):
        target = nodeID
        source = pSource
        if target != source:
            if isReversed:
                source, target = target, source
            paths = list(nx.all_simple_paths(G, source, target))
            for path in paths:
                allPaths.append(path)
    return allPaths


def findNode(child):
    nodeID = child.attrib['id'].replace('n', '')
    if nodeID == "91::0":
        pass
    for dataNode in child:
        tag = dataNode.tag.split('}', 1)[-1]
        if tag == 'data':
            key = dataNode.attrib['key']
            if key == "d6":
                d6Descendant = dataNode[0]
                if d6Descendant.tag.split('}', 1)[-1] == 'ShapeNode':
                    nodeName = d6Descendant[3].text.replace("\n", " ")
                    attrib = d6Descendant[1].attrib
                    if 'hasColor' in attrib and attrib['hasColor'] == 'false':
                        nodeValues[nodeID] = 0
                    else:
                        color = attrib['color'][1:]
                        if color in ['FFCC00', '99CCFF', 'FFFF00']:
                            nodeValues[nodeID] = 0
                        else:
                            R, G, B = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
                            nodeValues[nodeID] = -1 if R > (G + B) / 2 + COLOR_THRESHOLD else + 1 if G > (
                                    R + B) / 2 + COLOR_THRESHOLD else 0
                    nodes[nodeID] = nodeName
                else:
                    d6Descendant = d6Descendant[0][0]
                    for element in d6Descendant:
                        if element.tag.split('}', 1)[-1] == 'NodeLabel':
                            nodeName = d6Descendant[3].text.replace("\n", " ")
                            nodes[nodeID] = nodeName
        elif tag == 'graph':
            for dataNodeChild in dataNode:
                findNode(dataNodeChild)


def readFromGraphXML(inputFile):
    tree = ET.parse(inputFile)
    root = tree.getroot()

    # Iterate through elements
    children = root[len(root) - 2]
    for child in children:
        tag = child.tag.split('}', 1)[-1]
        if tag == 'node':
            findNode(child)
        elif tag == 'edge':
            edgeID = child.attrib['id'].replace('e', '')
            source = child.attrib['source'][1:].replace('n', '')
            target = child.attrib['target'][1:].replace('n', '')
            for data in child:
                if data.attrib['key'] == "d10":
                    edgeColor = data[0][1].attrib['color'][1:]
                    R, G, B = int(edgeColor[0:2], 16), int(edgeColor[2:4], 16), int(edgeColor[4:6], 16)
                    edgeValue = -1 if R > (G + B) / 2 + COLOR_THRESHOLD else +1
                    edges.append((source, target))
                    edgeValues[edgeID] = edgeValue

    return nodes, edges, edgeValues


def edgeValueString(edgeValue, is_simple = False):
    if not is_simple:
        return ":--->:" if edgeValue > 0 else ":--X->:"
    return "->" if edgeValue > 0 else "-X>"


def edgeValue(node1, node2):
    for idEdge, e in enumerate(edges):
        if e[0] == node1 and e[1] == node2:
            value = edgeValues.get(str(idEdge))
            if value:
                return value
    raise Exception("Edge not found!")


def rgb_print(text, r, g, b):
    return f"\033[38;2;{r};{g};{b}m{text}\033[0m"


def setTextColorByNodeProperties(text, cycleCorrelation, convenience):
    if convenience < 0:
        return rgb_print(text, 255, 0, 0) if cycleCorrelation > 0 else rgb_print(text, 255, 155, 155)
    if convenience > 0:
        return rgb_print(text, 0, 255, 0) if cycleCorrelation > 0 else rgb_print(text, 155, 255, 155)
    return rgb_print(text, 255, 255, 255) if cycleCorrelation > 0 else rgb_print(text, 96, 96, 96)


def getColorByNodeProperties(cycleCorrelation, convenience):
    if convenience < 0:
        return "#FF0000" if cycleCorrelation > 0 else "#FFAAAA"
    if convenience > 0:
        return "#00FF00" if cycleCorrelation > 0 else "#AAFFAA"
    return "#FFFFFF" if cycleCorrelation > 0 else "#777777"


def printPathsFromSourceToTarget(html_content, sourceNodeID, targetNodeID, sourceNode, targetNode):
    html_content += '<br>'
    html_content += f'<h1>Paths: {sourceNode} -> {targetNode}</h1>'
    # print(f"\n {Fore.RESET}Paths: {sourceNode} -> {targetNode}")
    all_paths = list(nx.all_simple_paths(G, source=sourceNodeID, target=targetNodeID))
    html_content = printNodes(all_paths, html_content)
    return html_content


def sortAlphabeticallyByJoiningNumericalStringLists(cycles, nodes):
    max_length = len(str(len(nodes))) + 1

    def sort_key(sublist):
        return ''.join(s.rjust(max_length, '0') for s in sublist)

    cycles = sorted(cycles, key=sort_key)
    return cycles


def printNode(path, pathNodeID, pathLen, cycleCorrelation, nodesToTraverse, hp, isPrintingToHTML):
    nodeID = path[pathNodeID % pathLen]
    nodesPrinted.add(nodeID)
    try:
        nodeName = nodes[nodeID]
        convenience = cycleCorrelation * nodeValues[nodeID]
        isSpecialNode = targetNode == nodeName or sourceNode == nodeName
        if isPrintingToHTML:
            hpTextStyle = ("background-color:black;" if isSpecialNode else "") + "color:" + getColorByNodeProperties(
                cycleCorrelation, convenience)
            hp += '<span style="' + hpTextStyle + '">' + nodeName + '</span>'
        if pathNodeID < nodesToTraverse - 1:
            edgeCorrelation = edgeValue(path[pathNodeID % pathLen], path[(pathNodeID + 1) % pathLen])
            cycleCorrelation *= edgeCorrelation
            if isPrintingToHTML:
                strConnector = edgeValueString(edgeCorrelation)
                hpTextStyle = "color:" + ("#AAAAFF" if edgeCorrelation < 0 else "#000000")
                hp += '<span style="' + hpTextStyle + '">' + strConnector + ' </span>'
    except KeyError as e:
        pass
    except UnicodeError as e:
        pass
    return cycleCorrelation, hp


def printNodes(all_paths, html_content, isCycle=False):
    isPrintingToHTML = ENABLE_NON_CYCLE_PRINTING or isCycle
    for pathID, path in enumerate(all_paths):
        cycleCorrelation, nodesToTraverse, pathLen, hp = initializePrintingNodes(path, isCycle)
        for pathNodeID in range(nodesToTraverse):
            cycleCorrelation, hp = printNode(path, pathNodeID, pathLen, cycleCorrelation, nodesToTraverse, hp,
                                             isPrintingToHTML)
        hp += '</span>'

        edgeCorrelationStr3 = ''
        if isCycle:
            try:
                color = getColorByNodeProperties(cycleCorrelation, cycleCorrelation * nodeValues[path[0]])
            except KeyError:
                html_content += f'<p style="color:red">ERROR: There is no nodeValue for {nodes(path[0])}</p>'
            else:
                edgeCorrelationStr3 = '<span style="color:' + color + '"> [V] </span>' if cycleCorrelation > 0 else '<span style="color:#FFFF22"> [=] </span>'
        html_content += f'<p><span style="color:white">{pathID: >3} ({len(path): >2}) {edgeCorrelationStr3}: </span>{hp}<span>{edgeCorrelationStr3}</span></p>'
    return html_content


def initializePrintingNodes(path, isCycle):
    hp = "<span>"
    cycleCorrelation = 1
    pathLen = len(path)
    nodesToTraverse = pathLen + (1 if isCycle else 0)
    return cycleCorrelation, nodesToTraverse, pathLen, hp


def printToFile(pHTMLContent: string):
    name = ''
    if not sourceNodeExists:
        name = FILE_NAME
    else:
        name = sourceNode
        if targetNodeExists:
            name += " - " + targetNode
    fileName = name + '.html'
    file_path = OUTPUT_FOLDER + fileName

    pHTMLContent = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-16">
        <title>{fileName}</title>
    </head>
    <body style="background-color:#1E1F22">
    """ + pHTMLContent

    pHTMLContent += """</body>
    </html>
    """

    with open(file_path, 'w') as f:
        f.write(pHTMLContent)
    print(f"HTML file '{fileName}' has been generated.")


def remove_nodes_from_graphml(p_input_file, p_output_file, nodesToKeep):
    # Register namespaces to ensure proper parsing
    ET.register_namespace('', 'http://graphml.graphdrawing.org/xmlns')
    ET.register_namespace('y', 'http://www.yworks.com/xml/graphml')
    ET.register_namespace('yed', 'http://www.yworks.com/xml/yed/3')

    # Parse the XML tree
    tree = ET.parse(p_input_file)
    root = tree.getroot()

    # Define namespaces for finding elements
    namespaces = {
        'graphml': 'http://graphml.graphdrawing.org/xmlns',
        'y': 'http://www.yworks.com/xml/graphml',
        'yed': 'http://www.yworks.com/xml/yed/3'
    }

    # Find the graph element
    graph = root.find('.//graphml:graph', namespaces)

    # Remove specified nodes
    if graph is not None:
        nodes_to_delete = set()
        for node in graph.findall('graphml:node', namespaces):
            node_id = node.get('id')
            if node_id not in nodesToKeep:
                nodes_to_delete.add(node)

        # Actually remove the nodes
        for node in nodes_to_delete:
            graph.remove(node)

        # Remove edges connected to removed nodes
        edges_to_delete = []
        for edge in graph.findall('graphml:edge', namespaces):
            source = edge.get('source')
            target = edge.get('target')

            if source not in nodesToKeep or target not in nodesToKeep:
                edges_to_delete.append(edge)

        # Actually remove the edges
        for edge in edges_to_delete:
            graph.remove(edge)

    # Write the modified XML
    tree.write(p_output_file, encoding='utf-8', xml_declaration=True)

    # Optionally, manually fix the XML to ensure proper formatting
    with open(p_output_file, 'r') as f:
        content = f.read()

    # Remove standalone attribute if needed
    content = content.replace(' standalone="no"', '')

    with open(p_output_file, 'w') as f:
        f.write(content)


def read_config_file(inputFile):
    with open(inputFile, "r") as f:
        sourceNode = f.readline().lower().split('=')[1].strip()
        targetNode = f.readline().lower().split('=')[1].strip()
        SHOW_ONLY_EDGES = f.readline().lower().split('=')[1].strip() == 'true'
        ENABLE_NON_CYCLE_PRINTING = f.readline().lower().split('=')[1].strip() == 'true'
        SORT_BY_LEN = f.readline().lower().split('=')[1].strip() == 'true'
        COLOR_THRESHOLD = int(f.readline().lower().split('=')[1].strip())
        FOLDER_PATH = f.readline().lower().split('=')[1].strip()
        FILE_NAME = f.readline().lower().split('=')[1].split('#')[0].strip()
    return sourceNode, targetNode, SHOW_ONLY_EDGES, ENABLE_NON_CYCLE_PRINTING, SORT_BY_LEN, COLOR_THRESHOLD, FOLDER_PATH,FILE_NAME

def show_edges(edges, html_content):
    html_content += '<br>'
    html_content += f'<h1 style="color:white;">Edges</h1>'
    for edgeID, e in enumerate(edges):
        try:
            edgeValueInt = edgeValues.get(str(edgeID))
            edgeValueStr = edgeValueString(edgeValueInt, True)
            html_content += f'<p><span style="color:#AAAAFF">{nodes[e[0]]}</span> <span style="color:#000000">{edgeValueStr}</span> <span style="color:#AAAAFF">{nodes[e[1]]}</span></p>'
        except KeyError as ke:
            print(f"KeyError for edge {e} with ID {edgeID}: {ke}")
        except Exception as ex:
            print(f"An error occurred for edge {e} with ID {edgeID}: {ex}")
    return html_content

if __name__ == '__main__':
    sourceNode, targetNode, SHOW_ONLY_EDGES, ENABLE_NON_CYCLE_PRINTING, SORT_BY_LEN, COLOR_THRESHOLD, FOLDER_PATH, FILE_NAME = read_config_file(inputFile)

    inputGraphMLFile = FOLDER_PATH + FILE_NAME + '.graphml'
    nodes, edges, edgeValues = readFromGraphXML(inputGraphMLFile)

    G = nx.DiGraph()
    G.add_nodes_from(nodes.keys())

    sourceNodeExists = False
    targetNodeExists = False
    sourceNodeID = -1
    targetNodeID = -1
    if sourceNode:
        for cycleNodeID in nodes:
            nodeKey = nodes[cycleNodeID]
            if nodeKey.lower() == sourceNode:
                sourceNodeID = cycleNodeID
                sourceNodeExists = True

        if not sourceNodeExists:
            raise Exception(f"Cound not find source node {sourceNode}")

    if targetNode:
        for cycleNodeID in nodes:
            nodeKey = nodes[cycleNodeID]
            if nodeKey.lower() == targetNode:
                targetNodeID = cycleNodeID
                targetNodeExists = True
        if not targetNodeExists:
            raise Exception(f"Cound not find target node {targetNode}")

    G.add_edges_from(edges)
    cycles = list(nx.simple_cycles(G))

    if targetNodeExists:
        cycles = [cycle for cycle in cycles if targetNodeID in cycle]
    if sourceNodeExists:
        cycles = [cycle for cycle in cycles if sourceNodeID in cycle]

        newCycles = []
        for cycle in cycles:
            newCycles.append(shiftTo(cycle, sourceNodeID))
        cycles = newCycles

    cycles = sortAlphabeticallyByJoiningNumericalStringLists(cycles, nodes)
    if SORT_BY_LEN:
        cycles = sorted(cycles, key=len)

    html_content = ''
    # with open('output.csv', "a+", encoding='utf-16be') as f:
    if sourceNode:
        if targetNode:
            s = f"Cycles: {Back.LIGHTBLACK_EX}{sourceNode}{Back.RESET} -> {Back.LIGHTBLACK_EX}{targetNode}{Back.RESET}\n"
            html_content += f'<h1 style="color:white;">Cycles: {sourceNode} -> {targetNode}</h1>'
        else:
            s = f"Cycles from: {Back.BLACK}{sourceNode}{Back.RESET}\n"
            html_content += f'<h1 style="color:white;">Cycles from: {sourceNode}</h1>'

    html_content = printNodes(cycles, html_content, True)

    if SHOW_ONLY_EDGES:
        html_content = show_edges(edges, html_content)
    else:
        if sourceNodeExists:
            if targetNodeExists:
                html_content = printPathsFromSourceToTarget(html_content, sourceNodeID, targetNodeID, sourceNode,
                                                            targetNode)
                html_content = printPathsFromSourceToTarget(html_content, targetNodeID, sourceNodeID, targetNode,
                                                            sourceNode)
            else:
                if ENABLE_NON_CYCLE_PRINTING:
                    html_content = show_all_paths(nodes, sourceNodeID, html_content, True)
                    html_content = show_all_paths(nodes, sourceNodeID, html_content)
                else:
                    findAllPathsForGraphML(nodes, sourceNodeID, True)
                    findAllPathsForGraphML(nodes, sourceNodeID)
        else:
            if not targetNodeExists:
                html_content = show_all_paths(nodes, sourceNodeID, html_content)
            
                

    printToFile(html_content)

    print(f"Node count: {len(nodesPrinted)} / {len(nodes)} ({int(100 * len(nodesPrinted) / len(nodes))}%)")
    # print (f"Edges count: {len(edgesPrinted)} / {len(edges)} ({int(100 * len(edgesPrinted) / len(edges))}%)")

    output_file = OUTPUT_FOLDER + 'output.graphml'
    nodesToKeep = [f'n{num}' for num in nodesPrinted]
    nodesToExclude = sorted([nodes[y] for y in [x for x in nodes if x not in nodesToKeep]])

    print('Irrelevant nodes:')
    for i in nodesToExclude:
        print(i, end=', ')
    remove_nodes_from_graphml(inputGraphMLFile, output_file, nodesToKeep)  # filter_graphml(, , nodesPrinted)


