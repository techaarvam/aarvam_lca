#include <stdio.h>

int countPaths(int x, int y) {
    if (x == 0 || y == 0) return 1;
    return countPaths(x - 1, y) + countPaths(x, y - 1);
}

int main() {
    int result = countPaths(5, 5);
    printf("%d\n", result);
    return 0;
}