# Building the capacitor array with nodes, edges (capacitors), and graphs (for the array)

class Node:
    def __init__(self, row: int, column: int, id: str):
        self.row = row
        self.column = column
        self.id = id

    def __repr__(self):
        return f"Node {self.id} at row {self.row}, column {self.column}"

    def __hash__(self):
        return hash((self.row, self.column))

    def __eq__(self, other):
        if isinstance(other, Node):
            return self.row == other.row and self.column == other.column
        return False

class CapacitorEdge:
    def __init__(self, source_node: Node, target_node: Node, capacitance: int, switch: bool):
        self.source = source_node
        self.target = target_node
        self.capacitance = capacitance
        self.switch = switch
        self.horizontal = self.source.row == self.target.row

    def get_other_node(self, node: Node):
        if self.source == node:
            return self.target
        elif self.target == node:
            return self.source
        else:
            raise ValueError("The provided node is not connected by this edge.")
        
    def __repr__(self):
        return f"Capacitor {'Horizontal' if self.horizontal else 'Vertical'} Edge connecting {self.source.id} and {self.target.id}, with capacitance {self.capacitance}. Switch is turned {'on' if self.switch else 'off'}"


class CapacitorGraph:
    def __init__(self, rows: int, columns: int):
        self.rows = rows
        self.columns = columns
        self.equivalent_capacitance = 0
        self.nodes = {}
        self.edges = []

    def build_array(self):
        # Add all nodes:
        for i in range(self.rows):
            for j in range(self.columns):
                id = f"r{i+1}c{j+1}"
                self.nodes[(i, j)] = Node(i, j, id)

        # Connect edges to nodes:
        for i in range(self.rows):
            for j in range(self.columns):
                current_node = self.nodes[(i, j)]
                # Connect node below if current node is not the bottom node
                if i < self.rows - 1:
                    self.edges.append(CapacitorEdge(current_node, self.nodes[(i+1, j)], capacitance=1, switch=False)) # Default capacitance is set to 1, will introduce unique capacitance later
                # Connect node to the right if current node is not the rightmost node
                if j < self.columns - 1:
                    self.edges.append(CapacitorEdge(current_node, self.nodes[(i, j+1)], capacitance=1, switch=False))

    def get_edges(self, node: Node):
        return [edge for edge in self.edges if edge.source == node or edge.target == node]



if __name__ == "__main__":
    graph = CapacitorGraph(rows=3, columns=3)
    graph.build_array()
    print("Nodes:")
    for node in graph.nodes.values():
        print(node)
    print("\nEdges:")
    for edge in graph.edges:
        print(edge)