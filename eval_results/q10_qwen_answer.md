This is a classic algorithmic puzzle that requires extending the standard "XOR to find unique element" technique.

### 1. Logical Deduction and Algorithm Design

#### The Core Insight: XOR Properties
Let the array be $A$. Let the three unique elements be $x, y, z$. All other elements appear exactly twice.
The XOR of the entire array, $S$, is:
$$ S = x \oplus y \oplus z $$
This is because $a \oplus a = 0$, so all paired elements cancel out.

#### The Challenge
In the standard problem (1 unique element), $S$ is the answer. Here, $S$ is the XOR of three unknowns. We cannot simply extract $x, y, z$ from $S$ directly without more information.

#### The Strategy: Bit Partitioning
We need to separate the unique elements into different groups so we can solve for them individually or in pairs.

1.  **Find a Distinguishing Bit**: Look at $S = x \oplus y \oplus z$. Since $x, y, z$ are distinct, $S \neq 0$. Therefore, there is at least one bit position $k$ where $S$ has a `1`.
    *   If $S$ has a `1` at bit $k$, it means an **odd number** of the unique elements $\{x, y, z\}$ have a `1` at bit $k$.
    *   Since there are 3 elements, the possible counts of `1`s at bit $k$ among $\{x, y, z\}$ are 1 or 3.

2.  **Partition the Array**:
    *   **Group 1**: All elements in $A$ that have a `1` at bit $k$.
    *   **Group 2**: All elements in $A$ that have a `0` at bit $k$.

    Let $S_1$ be the XOR of all elements in Group 1.
    Let $S_2$ be the XOR of all elements in Group 2.
    Note that $S_1 \oplus S_2 = S$.

3.  **Analyze the Groups**:
    The paired elements (those appearing twice) will always fall into the same group (both have bit $k$ as 0 or both as 1). Thus, they cancel out within their respective groups.
    
    The unique elements $\{x, y, z\}$ are distributed between Group 1 and Group 2 based on their $k$-th bit.
    
    There are two cases for the distribution of $\{x, y, z\}$:
    
    *   **Case A: All three unique elements have the same bit value at position $k$.**
        *   This implies all three are in Group 1 OR all three are in Group 2.
        *   If all are in Group 1: $S_1 = x \oplus y \oplus z = S$. And $S_2 = 0$.
        *   If all are in Group 2: $S_2 = x \oplus y \oplus z = S$. And $S_1 = 0$.
        *   *Problem*: We still have 3 unknowns in one group. We haven't separated them. We need to pick a *different* bit.

    *   **Case B: The unique elements are split.**
        *   Since the count of `1`s is odd (1 or 3), and we established that if it's 3 they are all together, the only other possibility is that **exactly one** unique element has a `1` at bit $k$, and the other two have `0`s.
        *   So, one unique element is in Group 1, and two unique elements are in Group 2.
        *   Let $u$ be the unique element in Group 1.
        *   Let $v, w$ be the unique elements in Group 2.
        *   Then $S_1 = u$.
        *   And $S_2 = v \oplus w$.

    **Wait, is Case A possible?**
    If $x, y, z$ all have `1` at bit $k$, then $S$ has `1` at bit $k$.
    If $x, y, z$ all have `0` at bit $k$, then $S$ has `0` at bit $k$.
    So, if we pick a bit $k$ where $S$ is `1`, it is **impossible** for all three to have `0`.
    It is possible for all three to have `1`.
    
    If all three have `1` at bit $k$:
    $S_1 = x \oplus y \oplus z = S$.
    $S_2 = 0$.
    This doesn't help us separate them. We need a bit that splits them.

    **Refined Strategy:**
    We need to find a bit position $k$ such that the unique elements are **not** all identical at that bit.
    
    Actually, there is a simpler, more robust approach often used for "3 unique elements":
    
    1. Calculate $S = x \oplus y \oplus z$.
    2. Find any bit $k$ where $S$ has a `1`.
    3. Partition the array into $G_1$ (bit $k$ is 1) and $G_0$ (bit $k$ is 0).
    4. Calculate $S_1 = \text{XOR}(G_1)$ and $S_0 = \text{XOR}(G_0)$.
    
    Now, consider the distribution of $x, y, z$:
    *   Since $S$ has a `1` at bit $k$, an odd number of $\{x,y,z\}$ have `1` at bit $k$.
    *   Possibility 1: One has `1`, two have `0`.
        *   $S_1$ contains the single unique element with `1`. So $S_1$ is one of the answers.
        *   $S_0$ contains the XOR of the other two.
        *   We can find the other two by solving $v \oplus w = S_0$ and knowing $v, w \neq S_1$. But how do we separate $v$ and $w$?
        *   We can use the fact that $v \oplus w = S_0$. We need another bit to split $v$ and $w$.
    *   Possibility 2: Three have `1`, zero have `0`.
        *   $S_1$ contains all three. $S_1 = x \oplus y \oplus z = S$.
        *   $S_0 = 0$.
        *   This case is problematic because we haven't separated anything.

    **How to handle Possibility 2?**
    If $S_0 = 0$, it means all unique elements were in $G_1$. This implies $x, y, z$ all have `1` at bit $k$.
    In this scenario, we simply pick a **different** bit $j$ where $S$ has a `1`? No, $S$ might only have one bit set? No, $x,y,z$ are distinct, so $S$ is non-zero. But $S$ could be a power of 2 (only one bit set).
    
    If $S$ has only one bit set (say bit $k$), then $x, y, z$ must all have `1` at bit $k$ (since an odd number must be 1, and if it were 1, the other two would be 0, making the XOR 1. If all three are 1, XOR is 1. Wait.
    $1 \oplus 0 \oplus 0 = 1$.
    $1 \oplus 1 \oplus 1 = 1$.
    
    If $S$ has only bit $k$ set:
    - Case 1: One `1`, two `0`s. Split works.
    - Case 2: Three `1`s. No split.
    
    How do we distinguish?
    If we partition by bit $k$ and get $S_0 = 0$, we know we are in Case 2 (all three in $G_1$).
    But wait, if we are in Case 2, $x, y, z$ all have `1` at bit $k$.
    We need to find another bit to split them.
    Do we know if such a bit exists?
    Yes, because $x, y, z$ are distinct. They cannot be identical in all bits.
    However, we are restricted to O(1) space. We can't store the values to check other bits easily without re-scanning.
    
    **Alternative Robust Approach:**
    
    1. Compute $S = x \oplus y \oplus z$.
    2. Find the **lowest set bit** in $S$. Let this be bit $k$.
    3. Partition the array into $G_1$ (bit $k$ is 1) and $G_0$ (bit $k$ is 0).
    4. Compute $S_1 = \text{XOR}(G_1)$ and $S_0 = \text{XOR}(G_0)$.
    
    **Analysis of $S_1$ and $S_0$:**
    
    *   **Scenario A**: $S_0 \neq 0$ and $S_1 \neq 0$.
        This implies the unique elements are split.
        Since the total count of `1`s at bit $k$ among uniques is odd (1 or 3), and they are split, it must be **1 in $G_1$ and 2 in $G_0$** (or vice versa).
        Without loss of generality, assume 1 unique in $G_1$ and 2 in $G_0$.
        Then $S_1$ is exactly one of the unique elements (let's call it $x$).
        $S_0$ is $y \oplus z$.
        Now we have $x$ and $y \oplus z$.
        We need to separate $y$ and $z$.
        We know $y \oplus z = S_0$.
        We also know $y, z \in G_0$.
        We need to find a bit $j$ where $y$ and $z$ differ.
        Since $y \neq z$, there is such a bit.
        However, we don't know $y$ and $z$ individually yet.
        
        Is there a way to find $y$ and $z$ from $S_0$ and the array?
        Yes. We can iterate through $G_0$ again? No, that's O(n) time, which is allowed. But we need O(1) space.
        
        Let's look at the structure again.
        If we have $x$ and $S_0 = y \oplus z$, can we find $y$ and $z$?
        We can pick any bit $j$ where $S_0$ has a `1`.
        Partition $G_0$ into $G_{0a}$ (bit $j$ is 1) and $G_{0b}$ (bit $j$ is 0).
        Compute $S_{0a} = \text{XOR}(G_{0a})$ and $S_{0b} = \text{XOR}(G_{0b})$.
        Since $y$ and $z$ differ at bit $j$, one is in $G_{0a}$ and one is in $G_{0b}$.
        The paired elements in $G_0$ will cancel out in their respective sub-groups.
        So $S_{0a}$ will be either $y$ or $z$, and $S_{0b}$ will be the other.
        
        So the algorithm is:
        1. $S = \text{XOR}(A)$.
        2. Find bit $k$ where $S$ has `1`.
        3. Partition $A$ by bit $k$. Get $S_1, S_0$.
        4. If $S_1 == 0$: All uniques in $G_0$. Swap roles, treat $G_0$ as the "main" group? No, if $S_1=0$, then $S_0 = S$. We are in the "all 3 in one group" case.
           If $S_0 == 0$: All uniques in $G_1$.
           
        Let's refine the "All 3 in one group" case.
        If $S_1 = 0$, then $x,y,z$ are all in $G_0$.
        We need to split $x,y,z$.
        We know $S_0 = x \oplus y \oplus z$.
        We need to find a bit $j$ that splits them.
        We can just pick **any** bit $j$ where $S_0$ has a `1`.
        Partition $G_0$ by bit $j$.
        Get $S_{0a}, S_{0b}$.
        Since $S_0$ has `1` at $j$, an odd number of $\{x,y,z\}$ have `1` at $j$.
        This splits them into 1 and 2.
        So one of $S_{0a}, S_{0b}$ is a single unique element, the other is XOR of two.
        Then we repeat the "separate the pair" step on the group with 2 uniques.
        
        **Unified Algorithm:**
        
        1. Compute $S = \text{XOR}(A)$.
        2. Find a bit $k$ where $S$ has `1`.
        3. Partition $A$ into $G_1$ (bit $k=1$) and $G_0$ (bit $k=0$).
        4. Compute $S_1 = \text{XOR}(G_1)$, $S_0 = \text{XOR}(G_0)$.
        
        Now we have two sub-problems. One group contains 1 unique, the other contains 2 uniques.
        (Note: It is impossible for one group to contain 0 and the other 3? 
        If $S$ has `1` at $k$, the count of `1`s among uniques is 1 or 3.
        If count is 1: One in $G_1$, two in $G_0$.
        If count is 3: Three in $G_1$, zero in $G_0$.
        
        So:
        - If $S_0 == 0$: The 3 uniques are in $G_1$. We need to split $G_1$.
        - If $S_1 == 0$: The 3 uniques are in $G_0$. We need to split $G_0$.
        - If $S_0 \neq 0$ and $S_1 \neq 0$: One group has 1 unique, the other has 2.
        
        **Step 5: Identify which group has 1 unique and which has 2.**
        We don't actually need to know *which* is which initially, we just need to extract the single one.
        
        Let's assume the standard case: One group